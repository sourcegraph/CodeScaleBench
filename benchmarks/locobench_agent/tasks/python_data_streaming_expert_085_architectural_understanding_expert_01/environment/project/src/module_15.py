```python
"""
PulseStream Nexus
=================
src/module_15.py

This module implements a reusable, streaming-first ETL pipeline that adheres to
the Clean-Architecture / Strategy-Pattern guidelines used across PulseStream
Nexus.  The pipeline

* consumes events from Kafka,
* optionally validates them,
* enriches them through a configurable transformation chain, and
* republishes the enriched payload downstream.

Operational concerns such as metrics, tracing and graceful shutdown handling
are baked in, while keeping the business rules (validators/transformers)
decoupled from the I/O layer.

NOTE:
    External dependencies are imported lazily where possible to keep unit tests
    light-weight.  For production, make sure the following extras are
    installed:

    pip install confluent-kafka pydantic prometheus-client
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from functools import cached_property
from types import FrameType
from typing import Any, Callable, Iterable, List, MutableMapping, Protocol

# -----------------------------------------------------------------------------
# 3rd-party (optional) --------------------------------------------------------
with suppress(ImportError):
    from confluent_kafka import Consumer, Producer, KafkaError  # type: ignore
with suppress(ImportError):
    from prometheus_client import Counter, Histogram, start_http_server  # type: ignore
with suppress(ImportError):
    from pydantic import BaseModel, ValidationError  # type: ignore

# -----------------------------------------------------------------------------
# Logging – globally shared across service ------------------------------------
LOG_LEVEL = os.getenv("PULSENEX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(threadName)s | %(message)s",
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Contracts (Strategy Pattern) -------------------------------------------------
class Transformer(Protocol):
    """A single ET(L) transformation step."""

    def __call__(self, event: "Event") -> "Event": ...


class Validator(Protocol):
    """Validates raw payload prior to model parsing."""

    def __call__(self, raw_payload: MutableMapping[str, Any]) -> None: ...


class Observer(Protocol):
    """Gets notified for every processed event (Observer Pattern)."""

    def notify(self, event: "Event") -> None: ...


# -----------------------------------------------------------------------------
# Domain Model ----------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class Event:
    """
    Domain entity that represents a single social interaction event.
    The schema intentionally remains minimal here – real-world deployment pulls
    this from the central Schema Registry.
    """

    event_id: str
    platform: str
    user_id: str
    text: str
    timestamp: float
    metadata: dict[str, Any]

    @classmethod
    def from_raw(cls, raw: MutableMapping[str, Any]) -> "Event":
        """Parse & validate raw payload into a strongly-typed Event object."""
        # If pydantic is installed, we leverage its robust validation.
        if "pydantic" in sys.modules:

            class _EventModel(BaseModel):
                event_id: str
                platform: str
                user_id: str
                text: str
                timestamp: float
                metadata: dict[str, Any] | None = {}

            model = _EventModel(**raw)  # type: ignore[arg-type]
            return cls(
                event_id=model.event_id,
                platform=model.platform,
                user_id=model.user_id,
                text=model.text,
                timestamp=model.timestamp,
                metadata=model.metadata or {},
            )

        # Fallback – simple, best-effort validation
        required = {"event_id", "platform", "user_id", "text", "timestamp"}
        missing = required - raw.keys()
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        return cls(
            event_id=str(raw["event_id"]),
            platform=str(raw["platform"]),
            user_id=str(raw["user_id"]),
            text=str(raw["text"]),
            timestamp=float(raw["timestamp"]),
            metadata=dict(raw.get("metadata", {})),
        )


# -----------------------------------------------------------------------------
# Built-in Transformers -------------------------------------------------------
class ToxicityTransformer:
    """
    Adds a naive toxicity score to the event based on simple heuristics.

    NOTE:
        For demonstration purposes only – replace with ML inference call to
        your actual toxicity model service (e.g., TensorFlow Serving).
    """

    TOXIC_WORDS = {"hate", "idiot", "kill", "trash"}

    def __call__(self, event: Event) -> Event:
        lower = event.text.lower()
        score = sum(1 for word in self.TOXIC_WORDS if word in lower) / len(
            self.TOXIC_WORDS
        )

        # Enrich metadata immutably (dataclass is frozen)
        new_meta = {**event.metadata, "toxicity_score": round(score, 2)}
        return Event(
            event_id=event.event_id,
            platform=event.platform,
            user_id=event.user_id,
            text=event.text,
            timestamp=event.timestamp,
            metadata=new_meta,
        )


class SentimentTransformer:
    """
    Dummy sentiment classifier using keyword counts.
    """

    POSITIVE = {"love", "great", "awesome", "happy"}
    NEGATIVE = {"hate", "bad", "sad", "angry"}

    def __call__(self, event: Event) -> Event:
        tokens = set(event.text.lower().split())
        pos = len(tokens & self.POSITIVE)
        neg = len(tokens & self.NEGATIVE)
        sentiment = "neutral"
        if pos > neg:
            sentiment = "positive"
        elif neg > pos:
            sentiment = "negative"

        new_meta = {**event.metadata, "sentiment": sentiment}
        return Event(
            event_id=event.event_id,
            platform=event.platform,
            user_id=event.user_id,
            text=event.text,
            timestamp=event.timestamp,
            metadata=new_meta,
        )


# -----------------------------------------------------------------------------
# Observers (for monitoring, metrics, etc.) -----------------------------------
class PrometheusObserver:
    """
    Records processed events & latency in Prometheus.

    Exposed via a dedicated metrics HTTP server.
    """

    EVENT_COUNTER = Counter(  # type: ignore[has-type]
        "pulsenex_events_total",
        "Total number of events processed",
        ["platform", "status"],
    )
    LATENCY_HISTOGRAM = Histogram(  # type: ignore[has-type]
        "pulsenex_event_latency_seconds",
        "End-to-end event processing latency",
        ["platform"],
    )

    def notify(self, event: Event) -> None:
        self.EVENT_COUNTER.labels(platform=event.platform, status="processed").inc()
        # In production, we would measure true latency (now-timestamp)
        self.LATENCY_HISTOGRAM.labels(platform=event.platform).observe(0.01)


# -----------------------------------------------------------------------------
# Pipeline Core ----------------------------------------------------------------
class StreamingETLPipeline:
    """
    Connects Validators, Transformers and Observers into a cohesive unit that
    runs forever (or until SIGTERM/SIGINT).
    """

    def __init__(
        self,
        *,
        kafka_consumer: "Consumer",
        kafka_producer: "Producer",
        destination_topic: str,
        validators: Iterable[Validator] | None = None,
        transformers: Iterable[Transformer] | None = None,
        observers: Iterable[Observer] | None = None,
        batch_size: int = 100,
        poll_timeout: float = 1.0,
    ) -> None:
        self._consumer = kafka_consumer
        self._producer = kafka_producer
        self._destination_topic = destination_topic
        self._validators = list(validators or [])
        self._transformers = list(transformers or [])
        self._observers = list(observers or [])
        self._batch_size = batch_size
        self._poll_timeout = poll_timeout
        self._stop_event = threading.Event()

    # ---------------------------------------------------------------------
    # Public API ----------------------------------------------------------
    def run_forever(self) -> None:
        logger.info("Startup complete – listening for events.")
        self._setup_signal_handlers()
        try:
            while not self._stop_event.is_set():
                self._process_batch()
        finally:
            self._shutdown()

    # ---------------------------------------------------------------------
    # Internal Helpers ----------------------------------------------------
    def _process_batch(self) -> None:
        messages = self._consumer.consume(num_messages=self._batch_size, timeout=self._poll_timeout)  # type: ignore[attr-defined]
        if not messages:
            return

        for msg in messages:
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka error: %s", msg.error())
                continue

            raw_payload: dict[str, Any] = self._parse_kafka_payload(msg.value())
            if raw_payload is None:
                continue  # malformed JSON, already logged

            if not self._run_validators(raw_payload):
                continue  # validator rejected

            try:
                event = Event.from_raw(raw_payload)
            except (ValueError, ValidationError) as exc:  # type: ignore[misc]
                logger.warning("Schema validation failed: %s", exc)
                continue

            for transformer in self._transformers:
                with self._timeit(event.platform):
                    event = transformer(event)

            self._publish(event)
            self._notify_observers(event)

        # Manual offset commit for at-least-once semantics
        self._consumer.commit(asynchronous=False)

    @staticmethod
    def _parse_kafka_payload(value: bytes) -> dict[str, Any] | None:
        try:
            return json.loads(value.decode("utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON payload: %s", exc)
            return None

    def _run_validators(self, raw_payload: dict[str, Any]) -> bool:
        for validator in self._validators:
            try:
                validator(raw_payload)
            except Exception as exc:
                logger.debug("Validator '%s' rejected payload: %s", validator, exc)
                return False
        return True

    def _publish(self, event: Event) -> None:
        try:
            self._producer.produce(
                topic=self._destination_topic,
                key=event.event_id,
                value=json.dumps(event.__dict__).encode("utf-8"),
            )
        except BufferError as exc:
            logger.error("Producer buffer full – dropping event %s: %s", event.event_id, exc)

    def _notify_observers(self, event: Event) -> None:
        for obs in self._observers:
            with suppress(Exception):
                obs.notify(event)

    # ---------------------------------------------------------------------
    # Context Managers / Utilities ---------------------------------------
    @dataclass
    class _Timer:
        start_time: float

        def __enter__(self) -> "_Timer":
            self.start_time = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            self.elapsed = time.perf_counter() - self.start_time  # type: ignore[attr-defined]

    def _timeit(self, platform: str) -> "_Timer":
        """
        Helper context manager that records elapsed time for the Prometheus
        histogram if the PrometheusObserver is used.
        """
        timer = self._Timer(time.perf_counter())

        def _finalize(timer: StreamingETLPipeline._Timer) -> None:  # noqa: D401
            elapsed = getattr(timer, "elapsed", None)
            if elapsed is not None:
                for obs in self._observers:
                    if isinstance(obs, PrometheusObserver):
                        PrometheusObserver.LATENCY_HISTOGRAM.labels(platform=platform).observe(elapsed)

        # Hook _finalize on exit
        timer.__exit__ = lambda exc_type, exc_val, exc_tb, t=timer: (  # type: ignore[assignment]
            _finalize(t)
        )
        return timer

    # ---------------------------------------------------------------------
    # Shutdown Handling ---------------------------------------------------
    def _setup_signal_handlers(self) -> None:
        def _handler(signo: int, frame: FrameType | None) -> None:  # noqa: D401
            logger.info("Received signal %s – shutting down gracefully.", signo)
            self._stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _handler)

    def _shutdown(self) -> None:
        logger.info("Flushing producer & closing consumer.")
        with suppress(Exception):
            self._producer.flush(5)
            self._consumer.close()


# -----------------------------------------------------------------------------
# Factories -------------------------------------------------------------------
def _build_kafka_consumer() -> "Consumer":
    if "confluent_kafka" not in sys.modules:
        raise RuntimeError("confluent-kafka must be installed for production run.")

    config = {
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "localhost:9092"),
        "group.id": os.getenv("KAFKA_GROUP", "pulsenex_etl"),
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }
    topics = os.getenv("KAFKA_SOURCE_TOPICS", "social.raw").split(",")

    consumer = Consumer(config)  # type: ignore[call-arg]
    consumer.subscribe(topics)
    return consumer


def _build_kafka_producer() -> "Producer":
    if "confluent_kafka" not in sys.modules:
        raise RuntimeError("confluent-kafka must be installed for production run.")

    config = {"bootstrap.servers": os.getenv("KAFKA_BROKERS", "localhost:9092")}
    return Producer(config)  # type: ignore[call-arg]


def _start_prometheus_server() -> None:
    if "prometheus_client" not in sys.modules:
        logger.warning("prometheus_client missing – metrics endpoint disabled.")
        return

    port = int(os.getenv("PULSENEX_METRICS_PORT", 9118))
    start_http_server(port)  # type: ignore[arg-type]
    logger.info("Prometheus metrics exporter running on :%d", port)


# -----------------------------------------------------------------------------
# Validators Example ----------------------------------------------------------
class LanguageValidator:
    """
    Rejects events not matching the configured language set.
    Expects a `metadata['lang']` property.
    """

    def __init__(self, allowed: Iterable[str] | None = None) -> None:
        self._allowed = {lang.lower() for lang in (allowed or {"en"})}

    def __call__(self, raw_payload: MutableMapping[str, Any]) -> None:
        lang = str(raw_payload.get("metadata", {}).get("lang", "unknown")).lower()
        if lang not in self._allowed:
            raise ValueError(f"Unsupported language '{lang}'")


# -----------------------------------------------------------------------------
# CLI Entrypoint --------------------------------------------------------------
def main() -> None:  # pragma: no cover
    # Guard against launching without kafka libs in development env
    if "confluent_kafka" not in sys.modules:
        logger.error("Missing 'confluent-kafka' – cannot start pipeline.")
        sys.exit(3)

    _start_prometheus_server()

    pipeline = StreamingETLPipeline(
        kafka_consumer=_build_kafka_consumer(),
        kafka_producer=_build_kafka_producer(),
        destination_topic=os.getenv("KAFKA_DEST_TOPIC", "social.enriched"),
        validators=[LanguageValidator({"en", "es"})],
        transformers=[ToxicityTransformer(), SentimentTransformer()],
        observers=[PrometheusObserver()],
        batch_size=int(os.getenv("PULSENEX_BATCH_SIZE", 100)),
        poll_timeout=float(os.getenv("PULSENEX_POLL_TIMEOUT", 1.0)),
    )
    pipeline.run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
```