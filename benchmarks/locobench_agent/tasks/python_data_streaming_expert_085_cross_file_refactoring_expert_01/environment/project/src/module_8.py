```python
"""
PulseStream Nexus – src.module_8
======================================================================
High-level, framework-agnostic processing pipeline for real-time social
events.  Implements a Strategy-based transformation chain as well as an
Observer hook-in for monitoring/alerting layers.  The module is meant
to be orchestrated by the data-ingestion service that feeds deserialized
broker messages (e.g. from Kafka) into `ProcessingEngine.process_stream`.

Notes
-----
* No network or disk I/O is performed directly within the pipeline,
  satisfying Clean Architecture boundaries.
* Great Expectations is optional; if unavailable, a fallback validator
  that only checks schema keys is used.
* All classes are self-contained and encourage unit testing in isolation.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence

try:
    import great_expectations as ge  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ge = None

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logger = logging.getLogger("pulstream.processing")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Domain entities
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Event:
    """
    Canonical representation of a social interaction event traversing the
    processing pipeline.
    """

    id: str
    network: str
    created_at: datetime
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_raw(raw: Dict[str, Any]) -> "Event":
        """
        Factory method converting a raw broker message (dict) into an Event
        object, ensuring required fields exist.
        """
        try:
            event_id = raw.get("id", str(uuid.uuid4()))
            network = raw["network"]
            created_at = datetime.fromisoformat(raw["created_at"])
            payload = raw["payload"]
        except (KeyError, ValueError) as exc:  # pragma: no cover
            raise ValidationError(f"Malformed raw event: {exc}") from exc
        return Event(id=event_id, network=network, created_at=created_at, payload=payload)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProcessingError(Exception):
    """Top-level exception thrown when a pipeline fails permanently."""


class ValidationError(ProcessingError):
    """Raised when an event fails any validation step."""


# ---------------------------------------------------------------------------
# Validation layer
# ---------------------------------------------------------------------------


class EventValidator(ABC):
    """
    Strategy interface for validating events before transformation occurs.
    """

    @abstractmethod
    def validate(self, event: Event) -> None:
        """Raise ValidationError if validation fails."""


class SchemaValidator(EventValidator):
    """
    Lightweight validator that asserts presence of required keys.
    Serves as a fallback when Great Expectations is not available.
    """

    required_keys: Sequence[str] = ("user_id", "text")

    def validate(self, event: Event) -> None:
        missing = [k for k in self.required_keys if k not in event.payload]
        if missing:
            raise ValidationError(f"Missing required keys in payload: {', '.join(missing)}")


class GxValidator(EventValidator):
    """
    Great Expectations-powered validator.  A minimal GE suite is built
    at runtime; in a real deployment, one would reference a versioned
    expectation suite stored in S3/DBFS/etc.
    """

    def __init__(self) -> None:
        if ge is None:  # pragma: no cover
            raise RuntimeError("great_expectations not installed")
        self.context = ge.DataContext.create(project_root_dir="/tmp/gx_context")
        self.expectation_suite_name = "pulsestream.event_payload"
        self._Bootstrap()

    def _Bootstrap(self) -> None:
        if not self.context.list_expectation_suite_names():
            self.context.add_expectation_suite(self.expectation_suite_name)

    def validate(self, event: Event) -> None:
        batch = self.context.datasources.add_pandas("in_memory").get_batch(data=[event.payload])
        result = self.context.run_validation_operator(
            "action_list_operator",
            assets_to_validate=[batch],
            run_name="pulsestream_inline",
        )
        if not result["success"]:
            raise ValidationError(f"Great Expectations validation failed: {result}")


# ---------------------------------------------------------------------------
# Transformation strategy layer
# ---------------------------------------------------------------------------


class TransformStrategy(ABC):
    """
    Strategy interface for mutating an Event in place or returning an
    enriched copy.  Implementation must not perform blocking I/O.
    """

    name: str

    @abstractmethod
    def transform(self, event: Event) -> Event:
        """Return a new, transformed Event instance."""


class SentimentTransform(TransformStrategy):
    name = "sentiment"

    def transform(self, event: Event) -> Event:
        text = event.payload.get("text", "")
        score = self._naive_sentiment(text)
        new_metadata = {**event.metadata, "sentiment_score": score}
        return Event(**{**event.__dict__, "metadata": new_metadata})

    @staticmethod
    def _naive_sentiment(text: str) -> float:
        # Placeholder for ML inference; using very naive rule for demo
        pos_words = ("great", "good", "love", "awesome", "😊")
        neg_words = ("bad", "hate", "terrible", "awful", "😡")
        score = 0.5
        score += 0.1 * sum(w in text.lower() for w in pos_words)
        score -= 0.1 * sum(w in text.lower() for w in neg_words)
        return max(0.0, min(1.0, score))


class ToxicityTransform(TransformStrategy):
    name = "toxicity"

    def transform(self, event: Event) -> Event:
        text = event.payload.get("text", "")
        toxic_keywords = ("idiot", "stupid", "hate", "kill")
        warnings = sum(k in text.lower() for k in toxic_keywords)
        toxicity_score = min(1.0, warnings * 0.25)
        new_metadata = {**event.metadata, "toxicity_score": toxicity_score}
        return Event(**{**event.__dict__, "metadata": new_metadata})


class ViralityTransform(TransformStrategy):
    name = "virality"

    def transform(self, event: Event) -> Event:
        metrics = event.payload.get("metrics", {})
        likes = metrics.get("likes", 0)
        shares = metrics.get("shares", 0)
        comments = metrics.get("comments", 0)
        virality = self._weighted_mean(likes, shares, comments)
        new_metadata = {**event.metadata, "virality_score": virality}
        return Event(**{**event.__dict__, "metadata": new_metadata})

    @staticmethod
    def _weighted_mean(likes: int, shares: int, comments: int) -> float:
        weights = {"likes": 0.2, "shares": 0.6, "comments": 0.2}
        total = likes + shares + comments or 1
        weighted = (
            likes * weights["likes"]
            + shares * weights["shares"]
            + comments * weights["comments"]
        )
        return min(1.0, weighted / total)


# ---------------------------------------------------------------------------
# Observer layer (Observer Pattern)
# ---------------------------------------------------------------------------


class EventObserver(ABC):
    """Observer that receives notifications during processing."""

    @abstractmethod
    def on_success(self, event: Event) -> None:
        ...

    @abstractmethod
    def on_failure(self, event: Event, exc: Exception) -> None:
        ...

    @abstractmethod
    def on_complete(self, processed: int, failed: int, duration_sec: float) -> None:
        ...


class LoggingObserver(EventObserver):
    """Logs each outcome; light-weight but verbose."""

    def on_success(self, event: Event) -> None:
        logger.debug("Processed event %s successfully.", event.id)

    def on_failure(self, event: Event, exc: Exception) -> None:
        logger.warning("Failed processing event %s: %s", event.id, exc)

    def on_complete(self, processed: int, failed: int, duration_sec: float) -> None:
        logger.info(
            "Stream completed – processed=%d failed=%d duration=%.2fs",
            processed,
            failed,
            duration_sec,
        )


class MetricsObserver(EventObserver):
    """
    Emits Prometheus metrics if the client is installed; otherwise acts
    as a no-op to guard against missing runtime dependencies.
    """

    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Histogram  # type: ignore
        except ModuleNotFoundError:  # pragma: no cover
            self.enabled = False
            return

        self.enabled = True
        self._success_counter = Counter("ps_event_success", "Successfully processed events")
        self._failure_counter = Counter("ps_event_failure", "Failed events")
        self._latency = Histogram("ps_processing_latency_seconds", "Event processing latency")

    def on_success(self, event: Event) -> None:
        if self.enabled:
            self._success_counter.inc()

    def on_failure(self, event: Event, exc: Exception) -> None:
        if self.enabled:
            self._failure_counter.inc()

    def on_complete(self, processed: int, failed: int, duration_sec: float) -> None:
        if self.enabled:
            # Record end-of-stream marker
            self._latency.observe(duration_sec)


# ---------------------------------------------------------------------------
# Pipeline / Engine
# ---------------------------------------------------------------------------


class ProcessingPipeline:
    """
    A composable pipeline that applies a series of validators followed by
    transformation strategies, while notifying attached observers.
    """

    def __init__(
        self,
        *,
        validators: Optional[List[EventValidator]] = None,
        transformers: Optional[List[TransformStrategy]] = None,
        observers: Optional[List[EventObserver]] = None,
    ) -> None:
        self._validators: List[EventValidator] = validators or [SchemaValidator()]
        self._transformers: List[TransformStrategy] = transformers or [
            SentimentTransform(),
            ToxicityTransform(),
            ViralityTransform(),
        ]
        self._observers: List[EventObserver] = observers or [LoggingObserver(), MetricsObserver()]

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def process(self, event: Event) -> Event:
        """
        Validate and transform the event.  Observers are notified of either
        success or failure.  Returns the final, transformed Event.
        """
        try:
            for validator in self._validators:
                validator.validate(event)

            for transformer in self._transformers:
                event = transformer.transform(event)

            self._notify_success(event)
            return event
        except Exception as exc:
            self._notify_failure(event, exc)
            raise

    # ---------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------

    def _notify_success(self, event: Event) -> None:
        for obs in self._observers:
            obs.on_success(event)

    def _notify_failure(self, event: Event, exc: Exception) -> None:
        for obs in self._observers:
            obs.on_failure(event, exc)

    def _notify_complete(self, processed: int, failed: int, duration_sec: float) -> None:
        for obs in self._observers:
            obs.on_complete(processed, failed, duration_sec)


class ProcessingEngine:
    """
    Orchestrates asynchronous streaming processing of events.  It consumes
    an `AsyncIterator[Dict]` delivering raw messages from an upstream
    broker adapter and converts them into `Event`s before handing them
    to the internal pipeline.

    Example
    -------
    >>> async def run():
    ...     async for result in ProcessingEngine().process_stream(source()):
    ...         print(result)
    """

    def __init__(
        self,
        pipeline: Optional[ProcessingPipeline] = None,
        *,
        max_concurrency: int = 64,
        graceful_shutdown_timeout: int = 30,
    ) -> None:
        self._pipeline = pipeline or ProcessingPipeline()
        self._max_concurrency = max_concurrency
        self._shutdown_timeout = graceful_shutdown_timeout

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    async def process_stream(self, stream: AsyncIterator[Dict[str, Any]]) -> AsyncIterator[Event]:
        """
        Asynchronously consume a stream of raw messages, yield enriched
        Events downstream (e.g., to another microservice or Kafka topic).
        """
        start_ts = time.perf_counter()
        processed = 0
        failed = 0

        async for raw in stream:
            try:
                event = Event.from_raw(raw)
            except ValidationError as exc:
                logger.warning("Dropped malformed raw message: %s", exc)
                failed += 1
                continue

            try:
                enriched = await self._submit_to_pool(event)
                processed += 1
                yield enriched
            except Exception:
                failed += 1  # already logged by pipeline

        duration = time.perf_counter() - start_ts
        self._pipeline._notify_complete(processed, failed, duration)

    # ---------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------

    async def _submit_to_pool(self, event: Event) -> Event:
        """
        Submit processing to a bounded semaphore to throttle concurrency.
        """
        loop = asyncio.get_event_loop()
        semaphore = getattr(self, "_semaphore", None)
        if semaphore is None:
            semaphore = self._semaphore = asyncio.Semaphore(self._max_concurrency)

        async with semaphore:
            return await loop.run_in_executor(None, self._pipeline.process, event)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


async def _demo_source(num_events: int = 10) -> AsyncIterator[Dict[str, Any]]:  # pragma: no cover
    """
    A toy async generator that yields fake social events. Useful for a
    quick manual test:

        python -m src.module_8
    """
    import random

    now = datetime.utcnow().isoformat()
    for i in range(num_events):
        yield {
            "id": str(uuid.uuid4()),
            "network": random.choice(["twitter", "reddit", "mastodon"]),
            "created_at": now,
            "payload": {
                "user_id": str(uuid.uuid4()),
                "text": random.choice(
                    [
                        "I love this product! 😊",
                        "You are an idiot and I hate you",
                        "Neutral statement for testing",
                        "This launch is awesome, great job team!",
                    ]
                ),
                "metrics": {
                    "likes": random.randint(0, 100),
                    "shares": random.randint(0, 50),
                    "comments": random.randint(0, 20),
                },
            },
        }
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Main (manual debug entrypoint)
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        engine = ProcessingEngine()
        async for ev in engine.process_stream(_demo_source(25)):
            print(f"[sink] -> {ev.id} sentiment={ev.metadata['sentiment_score']:.2f}")

    asyncio.run(_main())
```