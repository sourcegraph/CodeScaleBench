```python
"""
src/module_43.py

PulseStream Nexus – Real-time Event Processor
=============================================

This module wires together the *critical path* for near-real-time social
events.  It

1.  Consumes raw events from Kafka,
2.  Validates the payload against the schema registry,
3.  Enriches the event through a pluggable transformation pipeline, and
4.  Publishes the enriched event to a downstream topic.

The implementation purposefully avoids any framework-specific details so it
can be reused in batch jobs or unit tests.  Only thin adapters
(`confluent_kafka`, `prometheus_client`, `jsonschema`) are imported, and safe
fallbacks are provided in their absence to keep the code runnable in CI
environments where those heavy external dependencies may be unavailable.

Architecture patterns demonstrated:
  • Strategy Pattern  – transformation layer  
  • Observer Pattern  – event subscribers / metrics collectors  
  • Pipeline Pattern  – ordered execution of strategies  

Author: PulseStream Nexus Platform Team
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any, Dict, List, Protocol

# --------------------------------------------------------------------------- #
# Optional third-party deps:                                                   #
# --------------------------------------------------------------------------- #
try:
    from confluent_kafka import Consumer, Producer, KafkaException  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Fallback stubs to keep linting/happy-path tests functional
    class KafkaException(Exception):
        pass

    class _DummyKafkaIO:  # pylint: disable=too-few-public-methods
        def __init__(self, *_a, **_kw) -> None:
            pass

        def poll(self, *_a, **_kw):  # type: ignore
            return None

        def produce(self, *_a, **_kw):  # type: ignore
            pass

        def flush(self, *_a, **_kw):  # type: ignore
            pass

        def subscribe(self, *_a, **_kw):  # type: ignore
            pass

        def commit(self, *_a, **_kw):  # type: ignore
            pass

        def close(self) -> None:  # type: ignore
            pass

    Consumer = _DummyKafkaIO  # type: ignore
    Producer = _DummyKafkaIO  # type: ignore

try:
    from prometheus_client import Counter, Histogram  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Minimal fallbacks
    class _Noop:  # pylint: disable=too-few-public-methods
        def __init__(self, *_a, **_kw):
            pass

        def labels(self, *_a, **_kw):
            return self

        def inc(self, *_a, **_kw):
            pass

        def observe(self, *_a, **_kw):
            pass

    Counter = Histogram = _Noop  # type: ignore

try:
    from jsonschema import validate as json_validate, ValidationError  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    def json_validate(_instance: Any, _schema: Dict[str, Any]) -> None:  # type: ignore
        # Pass-through fallback (no actual validation).
        return

    class ValidationError(Exception):  # type: ignore
        pass


# --------------------------------------------------------------------------- #
# Logging Configuration                                                        #
# --------------------------------------------------------------------------- #

LOG_LEVEL = os.getenv("PULSESTREAM_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pulsestream.module_43")


# --------------------------------------------------------------------------- #
# Prometheus metrics                                                           #
# --------------------------------------------------------------------------- #

EVENTS_CONSUMED = Counter(
    "pulsestream_events_consumed_total",
    "Total number of raw events consumed",
    ["topic"],
)
EVENTS_PUBLISHED = Counter(
    "pulsestream_events_published_total",
    "Total number of enriched events published",
    ["topic"],
)
EVENTS_VALIDATION_FAILED = Counter(
    "pulsestream_events_validation_failed_total",
    "Number of events dropped due to schema validation errors",
    ["topic"],
)
EVENT_PROCESSING_LATENCY = Histogram(
    "pulsestream_event_processing_latency_seconds",
    "Histogram of end-to-end event processing latencies",
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1, 2, 5),
)


# --------------------------------------------------------------------------- #
# Schema validation                                                            #
# --------------------------------------------------------------------------- #

class SchemaValidator:
    """
    Very thin wrapper around `jsonschema.validate` or schema registry lookups.
    """

    def __init__(self, schema: Dict[str, Any]) -> None:
        self._schema = schema

    def validate(self, event: Dict[str, Any]) -> None:
        """Raise ValidationError on failure."""
        json_validate(instance=event, schema=self._schema)


# --------------------------------------------------------------------------- #
# Transformation Strategy Pattern                                              #
# --------------------------------------------------------------------------- #

class EventTransformation(Protocol):
    """Protocol every transformation must implement."""

    def __call__(self, event: Dict[str, Any]) -> Dict[str, Any]: ...


@dataclass
class SentimentAnalysisTransformation:
    """
    Extremely naive sentiment classifier (placeholder for actual model call).
    """

    positive_keywords: List[str] = field(default_factory=lambda: ["good", "great", "love", "awesome", "😊"])
    negative_keywords: List[str] = field(default_factory=lambda: ["bad", "terrible", "hate", "awful", "😡"])

    def __call__(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text: str = event.get("text", "")
        score = sum(1 for k in self.positive_keywords if k in text.lower()) - sum(
            1 for k in self.negative_keywords if k in text.lower()
        )
        sentiment = "neutral"
        if score > 0:
            sentiment = "positive"
        elif score < 0:
            sentiment = "negative"
        event["sentiment"] = {"label": sentiment, "score": score}
        logger.debug("SentimentAnalysisTransformation result=%s", event["sentiment"])
        return event


@dataclass
class ToxicityDetectionTransformation:
    """Simple toxicity detector stub."""

    toxic_keywords: List[str] = field(default_factory=lambda: ["idiot", "kill", "stupid", "dumb"])

    def __call__(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text: str = event.get("text", "")
        is_toxic = any(k in text.lower() for k in self.toxic_keywords)
        event["toxicity"] = {"is_toxic": is_toxic}
        logger.debug("ToxicityDetectionTransformation result=%s", event["toxicity"])
        return event


# --------------------------------------------------------------------------- #
# Real-time Processor                                                          #
# --------------------------------------------------------------------------- #

@dataclass
class ProcessorConfig:
    """
    Configuration for RealTimeEventProcessor.

    This dataclass allows easy serialization/deserialization if we ever decide
    to store processor configs in a central registry.
    """

    kafka_bootstrap: str = os.getenv("PULSESTREAM_KAFKA_BOOTSTRAP", "localhost:9092")
    consume_topic: str = os.getenv("PULSESTREAM_CONSUME_TOPIC", "social.raw")
    produce_topic: str = os.getenv("PULSESTREAM_PRODUCE_TOPIC", "social.enriched")
    group_id: str = os.getenv("PULSESTREAM_GROUP_ID", "pulsestream_enricher")
    max_queue_size: int = 10_000
    # JSON schema for simplistic demo purposes
    schema: Dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "text": {"type": "string"},
                "timestamp": {"type": "number"},
                "source": {"type": "string"},
            },
            "required": ["id", "text", "timestamp", "source"],
            "additionalProperties": True,
        }
    )


class RealTimeEventProcessor:
    """
    Bridges Kafka I/O, schema validation, transformation pipeline, metrics,
    and exception handling.  The design is single-threaded per *stage* to
    simplify reasoning, while keeping an internal queue to decouple the
    consumer from the transformation/publisher latency.
    """

    def __init__(
        self,
        config: ProcessorConfig,
        transformations: List[EventTransformation] | None = None,
    ) -> None:
        self._config = config
        self._queue: Queue[tuple[dict, float]] = Queue(maxsize=config.max_queue_size)
        self._stop_requested = threading.Event()

        self._consumer = Consumer(
            {
                "bootstrap.servers": config.kafka_bootstrap,
                "group.id": config.group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        self._producer = Producer({"bootstrap.servers": config.kafka_bootstrap})

        self._schema_validator = SchemaValidator(config.schema)

        # Default transformations chain
        if transformations is None:
            transformations = [
                SentimentAnalysisTransformation(),
                ToxicityDetectionTransformation(),
            ]
        self._transformations = transformations

    # --------------------------------------------------------------------- #
    # Public API                                                             #
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        """Start consumer & worker threads, block until interrupted."""
        logger.info(
            "Starting RealTimeEventProcessor | consume=%s → produce=%s",
            self._config.consume_topic,
            self._config.produce_topic,
        )
        self._consumer.subscribe([self._config.consume_topic])

        consumer_thread = threading.Thread(target=self._consume_loop, daemon=True)
        worker_thread = threading.Thread(target=self._worker_loop, daemon=True)

        consumer_thread.start()
        worker_thread.start()

        try:
            while consumer_thread.is_alive() and worker_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Initiating graceful shutdown…")
            self._stop_requested.set()

        consumer_thread.join()
        worker_thread.join()
        self._shutdown()

    # --------------------------------------------------------------------- #
    # Private helpers                                                        #
    # --------------------------------------------------------------------- #

    def _consume_loop(self) -> None:
        """Continuously poll Kafka and place events onto an internal queue."""
        logger.debug("Consumer thread started.")
        while not self._stop_requested.is_set():
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka error: %s", msg.error())
                continue

            start_ts = time.time()
            try:
                raw_event = json.loads(msg.value().decode("utf-8"))
            except json.JSONDecodeError as exc:
                logger.warning("Invalid JSON, skipping message: %s", exc)
                self._consumer.commit(message=msg, asynchronous=False)
                continue

            try:
                self._schema_validator.validate(raw_event)
            except ValidationError as exc:
                logger.warning(
                    "Schema validation failed, dropping event id=%s: %s",
                    raw_event.get("id"),
                    exc,
                )
                EVENTS_VALIDATION_FAILED.labels(topic=self._config.consume_topic).inc()
                self._consumer.commit(message=msg, asynchronous=False)
                continue

            try:
                self._queue.put_nowait((raw_event, start_ts))
                EVENTS_CONSUMED.labels(topic=self._config.consume_topic).inc()
                self._consumer.commit(message=msg, asynchronous=False)
            except queue.Full:
                logger.error("Internal queue full! Back-pressure needed.")
                # In a real system, we might pause partitions or employ circuit breaking.

        logger.debug("Consumer loop stopped.")

    def _worker_loop(self) -> None:
        """
        Dequeue validated events, run transformations, and publish to output
        Kafka topic.  Runs until stop event is set AND queue is drained.
        """
        logger.debug("Worker thread started.")
        while not self._stop_requested.is_set() or not self._queue.empty():
            try:
                event, ingest_ts = self._queue.get(timeout=1.0)
            except Empty:
                continue

            # Apply transformations in sequence
            for transform in self._transformations:
                try:
                    event = transform(event)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception(
                        "Transformation %s failed for event id=%s. Dropping. %s",
                        transform.__class__.__name__,
                        event.get("id"),
                        exc,
                    )
                    event = None
                    break

            if event is None:
                continue  # Drop faulty event

            # Measure latency
            latency = time.time() - ingest_ts
            EVENT_PROCESSING_LATENCY.observe(latency)

            self._publish(event)

        logger.debug("Worker loop stopped.")

    def _publish(self, event: Dict[str, Any]) -> None:
        try:
            self._producer.produce(
                topic=self._config.produce_topic,
                value=json.dumps(event).encode("utf-8"),
                on_delivery=self._delivery_report,  # type: ignore
            )
            EVENTS_PUBLISHED.labels(topic=self._config.produce_topic).inc()
        except BufferError as exc:
            logger.error("Local producer queue is full! Failed to publish: %s", exc)
        except KafkaException as exc:
            logger.exception("Kafka publish failed: %s", exc)

        self._producer.poll(0)  # trigger any available delivery callbacks

    def _delivery_report(self, err, msg):  # type: ignore
        if err is not None:
            logger.error("Delivery failed for message %s: %s", msg.key(), err)
        else:
            logger.debug(
                "Message delivered to %s [%d] @ offset %d",
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )

    def _shutdown(self) -> None:
        """Release external resources."""
        logger.info("Shutting down processor…")
        try:
            self._producer.flush(5.0)
        except Exception:  # pylint: disable=broad-except
            logger.warning("Producer flush failed during shutdown.", exc_info=True)
        self._consumer.close()
        logger.info("Processor successfully shut down.")


# --------------------------------------------------------------------------- #
# Entry point for local development / debugging                               #
# --------------------------------------------------------------------------- #

def _default_transformations() -> List[EventTransformation]:
    """
    Register default transformations.  Having this in a function avoids issues
    with mutable globals when module reloads in interactive environments.
    """
    return [
        SentimentAnalysisTransformation(),
        ToxicityDetectionTransformation(),
    ]


def main() -> None:
    """
    Run the processor with the default config.  Environment variables can be
    set to override configuration fields (see `ProcessorConfig`).
    """
    config = ProcessorConfig()
    processor = RealTimeEventProcessor(config=config, transformations=_default_transformations())
    processor.start()


if __name__ == "__main__":
    main()
```