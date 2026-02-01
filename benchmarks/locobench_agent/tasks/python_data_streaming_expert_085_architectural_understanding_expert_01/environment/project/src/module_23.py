```python
"""
src/module_23.py

PulseStream Nexus – Streaming Event Processor
=============================================

This module contains a production-grade implementation of a streaming
event-processor that fits into the Clean-Architecture, strategy-driven
design of PulseStream Nexus.  The processor

    * Ingests raw social-network events from Kafka (or a local fallback)
    * Validates payloads against a JSON schema
    * Enriches events through a configurable list of transformers
    * Publishes the final event to a set of observers (e.g. metrics sinks)

The code purposely keeps framework / I/O concerns at the edges so that
core business logic (validation, transformation, notification) remains
easy to unit-test and re-use in batch jobs or alternative transports.

The file is 100 % self-contained: if Kafka, jsonschema, or prometheus_client
are missing, lightweight fallbacks are used, allowing the module to run
in a degraded, yet functional, “demo mode”.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import queue
import random
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("PULSENEX_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

###############################################################################
# Domain Models
###############################################################################


@dataclass(frozen=True, slots=True)
class RawEvent:
    """
    Raw, pre-validated event as received from an external source.
    """

    payload: Dict[str, Any]
    partition: Optional[int] = None
    offset: Optional[int] = None
    received_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


@dataclass(frozen=True, slots=True)
class EnrichedEvent:
    """
    Event after passing validation and enrichment phase.
    """

    payload: Dict[str, Any]
    processed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


###############################################################################
# Strategy Interfaces
###############################################################################


class EventValidator(abc.ABC):
    """Validates events according to some policy."""

    @abc.abstractmethod
    def validate(self, event: RawEvent) -> None:
        """
        Validate the given event or raise an exception.

        Raises
        ------
        ValueError
            If validation fails.
        """
        raise NotImplementedError


class EventTransformer(abc.ABC):
    """Transforms / enriches incoming events."""

    @abc.abstractmethod
    def transform(self, event: EnrichedEvent) -> EnrichedEvent:
        raise NotImplementedError


class Observer(abc.ABC):
    """Observer that reacts to successfully processed events."""

    @abc.abstractmethod
    def update(self, event: EnrichedEvent) -> None:
        raise NotImplementedError


###############################################################################
# Validator Implementations
###############################################################################


class JsonSchemaValidator(EventValidator):
    """
    Validates an event against a JSON Schema.

    Uses the `jsonschema` package if available; otherwise, performs
    a minimalistic attribute check on required fields.
    """

    def __init__(self, schema: Dict[str, Any]):
        self._schema = schema
        try:
            from jsonschema import Draft7Validator  # type: ignore
        except ImportError:  # pragma: no cover
            LOGGER.warning(
                "jsonschema package not installed – falling back "
                "to naive field-presence validation."
            )
            self._validator = None
        else:
            self._validator = Draft7Validator(schema)

    # --------------------------------------------------------------------- #

    def validate(self, event: RawEvent) -> None:  # noqa: D401, PLR0911
        if not self._validator:
            # Fallback: just make sure required fields exist
            required = self._schema.get("required", [])
            missing = [field for field in required if field not in event.payload]
            if missing:
                raise ValueError(f"Missing required fields: {missing}")
            return

        errors = sorted(self._validator.iter_errors(event.payload), key=str)
        if errors:
            err_txt = "; ".join(e.message for e in errors[:3])
            raise ValueError(f"Schema validation failed: {err_txt}")


###############################################################################
# Transformer Implementations
###############################################################################


class SentimentTransformer(EventTransformer):
    """
    Adds a very simple sentiment score.  In production we could
    integrate with `textblob`, spaCy, or a custom ML model.
    """

    def __init__(self) -> None:
        try:
            from textblob import TextBlob  # type: ignore
        except ImportError:  # pragma: no cover
            LOGGER.info("TextBlob missing – using naive sentiment analyser.")
            self._analyser = None
        else:
            self._analyser = TextBlob

    # ------------------------------------------------------------------ #

    def transform(self, event: EnrichedEvent) -> EnrichedEvent:
        text: str = event.payload.get("text", "")
        score: float
        if self._analyser:
            score = float(self._analyser(text).sentiment.polarity)
        else:
            # Naive approach: positive words – negative words
            positive = {"good", "great", "love", "excellent", "awesome"}
            negative = {"bad", "hate", "terrible", "awful", "worst"}
            pos_hits = sum(word in text.lower() for word in positive)
            neg_hits = sum(word in text.lower() for word in negative)
            score = (pos_hits - neg_hits) / max(len(text.split()), 1)

        enriched_payload = {**event.payload, "sentiment": score}
        return EnrichedEvent(payload=enriched_payload, processed_at=event.processed_at)


###############################################################################
# Observer Implementations
###############################################################################


class PrometheusMetricsObserver(Observer):
    """
    Publishes event metrics to Prometheus.  Falls back to a
    simple in-memory counter when the library is missing.
    """

    def __init__(self, metric_name: str = "pulsestream_events_total"):
        self._metric_name = metric_name
        try:
            from prometheus_client import Counter  # type: ignore
        except ImportError:  # pragma: no cover
            LOGGER.warning(
                "prometheus_client not installed – metrics stored locally."
            )
            self._counter = None
            self._local_count: int = 0
        else:
            self._counter = Counter(metric_name, "Total processed events")

    # ------------------------------------------------------------------ #

    def update(self, event: EnrichedEvent) -> None:
        if self._counter:
            self._counter.inc()
        else:
            self._local_count += 1
            if self._local_count % 100 == 0:
                LOGGER.info("Processed %s events (local counter).", self._local_count)


###############################################################################
# Processor Configuration
###############################################################################


@dataclass(slots=True)
class ProcessorConfig:
    """
    Configuration for `StreamingEventProcessor`.
    """

    topic: str = "social-events"
    group_id: str = "pulse-nexus"
    bootstrap_servers: str = "localhost:9092"
    enable_auto_commit: bool = False
    max_retries: int = 3
    backoff_seconds: float = 1.0
    poll_timeout: float = 1.0  # seconds
    graceful_shutdown: float = 2.0  # seconds for flush


###############################################################################
# Processor Implementation
###############################################################################


class StreamingEventProcessor:
    """
    Drives the end-to-end flow:

        Kafka → Validator → Transformers* → Observers*
    """

    def __init__(
        self,
        validator: EventValidator,
        transformers: Iterable[EventTransformer] | None = None,
        observers: Iterable[Observer] | None = None,
        config: ProcessorConfig | None = None,
    ) -> None:
        self._validator = validator
        self._transformers = list(transformers or [])
        self._observers = list(observers or [])
        self._config = config or ProcessorConfig()
        self._consumer = self._build_consumer()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Kafka consumer creation
    # ------------------------------------------------------------------ #

    def _build_consumer(self):  # noqa: D401
        """
        Build the Kafka consumer and subscribe to topic, or return a
        local in-memory queue when Kafka libs are unavailable.
        """
        try:
            from confluent_kafka import Consumer  # type: ignore
        except ImportError:  # pragma: no cover
            LOGGER.warning(
                "confluent-kafka not installed – using LocalQueueConsumer."
            )
            return _LocalQueueConsumer(self._config.topic)
        else:
            conf = {
                "bootstrap.servers": self._config.bootstrap_servers,
                "group.id": self._config.group_id,
                "enable.auto.commit": self._config.enable_auto_commit,
                "auto.offset.reset": "earliest",
            }
            consumer = Consumer(conf)
            consumer.subscribe([self._config.topic])
            return consumer

    # ------------------------------------------------------------------ #

    def _process_record(self, raw_payload: str, **meta: Any) -> None:
        try:
            data = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Invalid JSON: %s", exc)
            return

        raw_event = RawEvent(payload=data, partition=meta.get("partition"), offset=meta.get("offset"))

        # Validation
        try:
            self._validator.validate(raw_event)
        except ValueError as exc:
            LOGGER.warning("Validation error: %s", exc)
            return

        # Enrichment
        enriched: EnrichedEvent = EnrichedEvent(payload=raw_event.payload)
        for transformer in self._transformers:
            try:
                enriched = transformer.transform(enriched)
            except Exception as exc:  # pragma: no cover – catch-all
                LOGGER.exception("Transformer %s failed: %s", transformer, exc)
                return

        # Notify observers
        for observer in self._observers:
            with suppress(Exception):
                observer.update(enriched)

        LOGGER.debug("Successfully processed event: %s", enriched.payload.get("id", "<no-id>"))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running.is_set():
            LOGGER.warning("Processor already running.")
            return

        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        LOGGER.info("StreamingEventProcessor started.")

    def _run_loop(self) -> None:
        backoff = self._config.backoff_seconds
        while self._running.is_set():
            try:
                # Consumer abstraction
                message = self._consumer.poll(self._config.poll_timeout)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Poll failed: %s – backing off %.2fs", exc, backoff)
                time.sleep(backoff)
                continue

            if message is None:
                continue  # poll timeout

            # LocalQueueConsumer returns already decoded dicts
            if isinstance(message, dict):
                self._process_record(json.dumps(message))
                continue

            # confluent_kafka.Message
            if message.error():
                LOGGER.error("Kafka error: %s", message.error())
                continue

            self._process_record(
                message.value().decode("utf-8"),
                partition=message.partition(),
                offset=message.offset(),
            )

    # ------------------------------------------------------------------ #

    def stop(self) -> None:
        self._running.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(self._config.graceful_shutdown)

        # Flush / close consumer
        if hasattr(self._consumer, "close"):
            with suppress(Exception):
                self._consumer.close()

        LOGGER.info("StreamingEventProcessor stopped.")

    # Context-manager sugar
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "StreamingEventProcessor":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: D401, ANN001
        self.stop()


###############################################################################
# Local Fallback Implementations
###############################################################################


class _LocalQueueConsumer:
    """
    Drop-in replacement for a Kafka consumer.  Other threads can
    feed events via `.put(...)`.
    """

    def __init__(self, topic: str):
        self._queue: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=10_000)
        self._topic = topic

        # Start a background thread that synthesizes fake events
        thread = threading.Thread(target=self._generate_fake_events, daemon=True)
        thread.start()

    # ------------------------------------------------------------------ #

    def put(self, msg: dict[str, Any]) -> None:  # noqa: D401
        self._queue.put(msg)

    def poll(self, timeout: float | None = None):  # noqa: D401
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:  # noqa: D401
        pass

    # ------------------------------------------------------------------ #
    # Internal testing helper
    # ------------------------------------------------------------------ #

    def _generate_fake_events(self) -> None:
        """
        Pushes random demo events into the queue when running in demo mode.
        """
        sentiments = ["I love this!", "This is awful...", "Neutral statement."]
        while True:
            event = {
                "id": random.randint(1, 1_000_000),
                "user": f"user_{random.randint(1, 1_000)}",
                "text": random.choice(sentiments),
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            }
            self.put(event)
            time.sleep(random.uniform(0.1, 1.0))


###############################################################################
# Convenience launcher
###############################################################################


def _build_default_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "user", "text", "ts"],
        "properties": {
            "id": {"type": "integer"},
            "user": {"type": "string"},
            "text": {"type": "string"},
            "ts": {"type": "string", "format": "date-time"},
        },
    }


def build_default_processor() -> StreamingEventProcessor:
    """
    Assemble a processor with sensible defaults that can be used
    both in production and local development.
    """
    validator = JsonSchemaValidator(_build_default_schema())
    transformers = [SentimentTransformer()]
    observers = [PrometheusMetricsObserver()]
    return StreamingEventProcessor(
        validator=validator,
        transformers=transformers,
        observers=observers,
    )


if __name__ == "__main__":  # pragma: no cover
    """
    Local demo entry-point::

        $ python -m src.module_23

    The processor will run against an in-memory queue, feeding itself
    synthetic events.  Stop with CTRL-C.
    """
    processor = build_default_processor()
    try:
        with processor:
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user – shutting down.")
```