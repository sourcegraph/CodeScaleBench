```python
"""
PulseStream Nexus – module_53
--------------------------------
High-level enrichment micro-service that consumes raw social events from an
ingress topic, executes a configurable chain of transformations
(sentiment, toxicity and virality scoring) and publishes the enriched payload
to a downstream topic.

Clean-architecture notes
~~~~~~~~~~~~~~~~~~~~~~~~
    • domain           – immutable event objects + pure transformation logic
    • infrastructure   – Kafka I/O, Prometheus metrics, log formatting, etc.
    • application      – Orchestrates domain + infra; entry-point for service

This file purposely keeps framework specific code (Kafka, Prometheus) at the
boundaries and allows them to fail gracefully when a dependency is missing so
that pure-python unit-tests remain hermetic.
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Dict, Iterable, List, Sequence

# --------------------------------------------------------------------------- #
# Optional, third-party dependencies (fail gracefully when not available)
# --------------------------------------------------------------------------- #
try:
    # confluent_kafka provides the high-performance clients used in production.
    from confluent_kafka import Consumer, Producer, KafkaException  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Consumer = Producer = KafkaException = None  # type: ignore

try:
    from prometheus_client import Counter, Histogram, start_http_server  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Minimal no-op fallbacks keep the public API identical for tests.
    class _NoOp:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):
            pass

        def inc(self, *_):
            pass

        def observe(self, *_):
            pass

    Counter = Histogram = _NoOp  # type: ignore

    def start_http_server(*_, **__):  # type: ignore
        pass


# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #
LOG_LEVEL = os.getenv("PULSESTREAM_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s — [%(levelname)s] — %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("module_53")  # pylint: disable=invalid-name

# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
EVENTS_CONSUMED = Counter("psn_events_consumed_total", "Events consumed from ingress")
EVENTS_PUBLISHED = Counter("psn_events_published_total", "Events published downstream")
EVENT_ERRORS = Counter("psn_event_errors_total", "Exceptions raised during processing")

PROCESSING_TIME = Histogram(
    "psn_event_processing_seconds",
    "Latency distribution of event processing step",
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
        10,
    ),
)

# --------------------------------------------------------------------------- #
# Domain objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SocialEvent:
    """Immutable representation of an individual social event."""

    event_id: str
    network: str
    author_id: str
    content: str
    created_at: datetime

    @staticmethod
    def from_raw(payload: Dict[str, Any]) -> "SocialEvent":
        """Factory that converts a raw dict into a SocialEvent instance."""
        return SocialEvent(
            event_id=str(payload["event_id"]),
            network=str(payload["network"]),
            author_id=str(payload["author_id"]),
            content=str(payload["content"]),
            created_at=datetime.fromisoformat(payload["created_at"]).astimezone(
                timezone.utc
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert dataclass to plain dict for serialization."""
        return asdict(self)


# --------------------------------------------------------------------------- #
# Transformation strategy pattern
# --------------------------------------------------------------------------- #
class TransformationStrategy(ABC):
    """Strategy interface for event enrichment steps."""

    @abstractmethod
    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Apply transformation and return updated payload (must be pure)."""


class SentimentTransformer(TransformationStrategy):
    """Adds 'sentiment_score' in range [-1, 1] based on rudimentary heuristics."""

    POSITIVE_WORDS = {"love", "great", "fantastic", "happy", "excellent", "good"}
    NEGATIVE_WORDS = {"hate", "terrible", "awful", "sad", "bad", "worse"}

    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        content = event.get("content", "").lower()
        pos = sum(word in content for word in self.POSITIVE_WORDS)
        neg = sum(word in content for word in self.NEGATIVE_WORDS)
        score = 0.0
        if pos + neg > 0:
            score = (pos - neg) / (pos + neg)
        event["sentiment_score"] = round(score, 3)
        return event


class ToxicityTransformer(TransformationStrategy):
    """
    Adds 'toxicity_score' in range [0, 1].

    NOTE: For demo purposes we use keyword heuristics. In production, a
    dedicated ML model hosted behind an http endpoint is invoked.
    """

    TOXIC_WORDS = {"idiot", "moron", "stupid", "trash"}

    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        content = event.get("content", "").lower()
        toxic_count = sum(word in content for word in self.TOXIC_WORDS)
        length = max(len(content.split()), 1)
        event["toxicity_score"] = round(min(toxic_count / length, 1.0), 3)
        return event


class ViralityTransformer(TransformationStrategy):
    """Adds a naive 'virality_score' to estimate potential reach."""

    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        # For simplicity, randomly simulate virality based on message length
        length_factor = min(len(event.get("content", "")) / 280, 1.0)
        event["virality_score"] = round(random.random() * length_factor, 3)
        return event


# --------------------------------------------------------------------------- #
# Transformer pipeline
# --------------------------------------------------------------------------- #
class TransformerPipeline:
    """Composable pipeline that executes a sequence of strategies."""

    def __init__(self, strategies: Sequence[TransformationStrategy]) -> None:
        self._strategies: List[TransformationStrategy] = list(strategies)
        logger.debug("Pipeline initialized with %d strategies", len(self._strategies))

    def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Apply all registered strategies to the event."""
        with PROCESSING_TIME.time():  # prometheus histogram decorator
            for strategy in self._strategies:
                event = strategy.transform(event)
            return event


# --------------------------------------------------------------------------- #
# Infrastructure: Kafka client wrappers
# --------------------------------------------------------------------------- #
class _KafkaUnavailable(RuntimeError):
    """Raised when confluent_kafka is not installed."""

    pass


@dataclass
class KafkaConfig:
    """Hive of all config options for Kafka IO."""

    brokers: str = os.getenv("PULSESTREAM_KAFKA_BROKERS", "localhost:9092")
    group_id: str = os.getenv("PULSESTREAM_KAFKA_GROUP", "psn-module-53")
    auto_offset_reset: str = os.getenv("PULSESTREAM_KAFKA_RESET", "earliest")
    enable_auto_commit: bool = True
    security_protocol: str | None = os.getenv("PULSESTREAM_KAFKA_SECURITY_PROTOCOL")
    ssl_cafile: str | None = os.getenv("PULSESTREAM_KAFKA_SSL_CAFILE")
    ssl_certfile: str | None = os.getenv("PULSESTREAM_KAFKA_SSL_CERTFILE")
    ssl_keyfile: str | None = os.getenv("PULSESTREAM_KAFKA_SSL_KEYFILE")

    def consumer_conf(self) -> Dict[str, Any]:
        """Render confluent_kafka Consumer config."""
        base = {
            "bootstrap.servers": self.brokers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
        }
        if self.security_protocol:
            base["security.protocol"] = self.security_protocol
            if self.security_protocol.startswith("SSL"):
                base["ssl.ca.location"] = self.ssl_cafile
                base["ssl.certificate.location"] = self.ssl_certfile
                base["ssl.key.location"] = self.ssl_keyfile
        return base

    def producer_conf(self) -> Dict[str, Any]:
        """Render confluent_kafka Producer config."""
        return {"bootstrap.servers": self.brokers}


class KafkaClient:
    """Thin wrapper that hides confluent_kafka specifics and provides batch APIs."""

    def __init__(self, config: KafkaConfig, ingress: str, egress: str) -> None:
        if Consumer is None or Producer is None:  # pragma: no cover
            raise _KafkaUnavailable(
                "confluent_kafka package is required for KafkaClient but "
                "could not be imported. Install via `pip install confluent-kafka`."
            )
        self._consumer = Consumer(config.consumer_conf())
        self._consumer.subscribe([ingress])
        self._producer = Producer(config.producer_conf())
        self._egress_topic = egress
        logger.info("Kafka client initialized (group=%s)", config.group_id)

    def fetch(self, timeout: float = 1.0, max_records: int = 500) -> Iterable[Dict]:
        """Yield up to `max_records` messages as JSON dicts."""
        records: List[Dict[str, Any]] = []
        for _ in range(max_records):
            msg = self._consumer.poll(timeout=timeout)
            if msg is None:
                break
            if msg.error():
                logger.error("Kafka error: %s", msg.error())
                continue
            try:
                payload = json.loads(msg.value())
                records.append(payload)
            except json.JSONDecodeError as exc:
                logger.warning("Malformed JSON payload skipped: %s", exc)
        EVENTS_CONSUMED.inc(len(records))
        return records

    def publish(self, events: Sequence[Dict[str, Any]]) -> None:
        for event in events:
            self._producer.produce(self._egress_topic, json.dumps(event).encode())
        self._producer.flush()
        EVENTS_PUBLISHED.inc(len(events))

    def close(self) -> None:
        self._consumer.close()
        logger.info("Kafka consumer closed.")


# --------------------------------------------------------------------------- #
# Application orchestration
# --------------------------------------------------------------------------- #
class EnrichmentService:
    """Long-running worker that enriches events in near real-time."""

    def __init__(
        self,
        broker: KafkaClient,
        pipeline: TransformerPipeline,
        batch_size: int = 100,
        shutdown_event: Event | None = None,
    ) -> None:
        self._broker = broker
        self._pipeline = pipeline
        self._batch_size = batch_size
        self._shutdown_event = shutdown_event or Event()

    def start(self) -> None:
        """Kick off the service loop (blocking)."""
        logger.info("Enrichment service started")
        while not self._shutdown_event.is_set():
            try:
                raw_events = list(self._broker.fetch(max_records=self._batch_size))
                if not raw_events:
                    continue

                enriched_events = []
                for raw in raw_events:
                    try:
                        domain_event = SocialEvent.from_raw(raw)
                        enriched_payload = self._pipeline.process(
                            domain_event.to_dict()
                        )
                        enriched_events.append(enriched_payload)
                    except Exception as exc:  # pylint: disable=broad-except
                        EVENT_ERRORS.inc()
                        logger.exception(
                            "Failed processing event_id=%s network=%s: %s",
                            raw.get("event_id"),
                            raw.get("network"),
                            exc,
                        )
                if enriched_events:
                    self._broker.publish(enriched_events)
            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as exc:  # pylint: disable=broad-except
                # top-level guard; service must stay alive
                logger.exception("Unexpected exception in service loop: %s", exc)
                time.sleep(5)

        self._broker.close()
        logger.info("Enrichment service stopped gracefully")


# --------------------------------------------------------------------------- #
# Main bootstrap
# --------------------------------------------------------------------------- #
def _init_signal_handlers(shutdown_event: Event) -> None:
    def _handler(signum, _stackframe):  # type: ignore
        logger.info("Received signal %s – shutting down.", signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handler)   # CTRL+C
    signal.signal(signal.SIGTERM, _handler)  # kill PID


def main() -> None:  # pragma: no cover
    """CLI entrance when running `python -m src.module_53`."""
    # Kick off Prometheus exporter before heavy lifting starts.
    metrics_port = int(os.getenv("PULSESTREAM_PROM_PORT", "9000"))
    start_http_server(metrics_port)
    logger.info("Prometheus metrics exposed on :%d", metrics_port)

    kafka_ingress = os.getenv("PULSESTREAM_INGRESS_TOPIC", "psn.raw.social")
    kafka_egress = os.getenv("PULSESTREAM_EGRESS_TOPIC", "psn.enriched.social")

    config = KafkaConfig()
    try:
        kafka_client = KafkaClient(config, kafka_ingress, kafka_egress)
    except _KafkaUnavailable as exc:
        logger.critical(exc)
        sys.exit(1)

    # Build transformation pipeline
    pipeline = TransformerPipeline(
        [
            SentimentTransformer(),
            ToxicityTransformer(),
            ViralityTransformer(),
        ]
    )

    shutdown_event = Event()
    _init_signal_handlers(shutdown_event)

    service = EnrichmentService(kafka_client, pipeline, shutdown_event=shutdown_event)

    # Optionally run worker in a thread when embedded, or block otherwise
    if os.getenv("PULSESTREAM_RUN_AS_THREAD"):
        Thread(target=service.start, daemon=True).start()
    else:
        service.start()


if __name__ == "__main__":
    main()
```