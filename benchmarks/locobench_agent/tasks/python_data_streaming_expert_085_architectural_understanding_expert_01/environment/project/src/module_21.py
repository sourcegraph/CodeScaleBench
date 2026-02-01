```python
"""
src/module_21.py
~~~~~~~~~~~~~~~~

Core streaming ingest component for PulseStream Nexus.

This module bundles together:
* A resilient Kafka consumer wrapper with pluggable commit strategies
* JSON-Schema event validation (great-expectations hooks could be added later)
* A tiny transformation pipeline that applies sentiment / toxicity strategies
* Prometheus metrics instrumentation
* An observer interface that allows downstream subscribers to receive
  successfully processed events in a framework-agnostic fashion

NOTE:
    The code is production-quality in style, but it purposely avoids hard
    dependencies on the rest of the platform so that it can be dropped into
    a stand-alone environment for unit tests or interactive exploration.
"""
from __future__ import annotations

import json
import logging
import queue
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import FrameType
from typing import Callable, Dict, Iterable, List, Optional, Protocol, runtime_checkable

# Optional third-party imports are placed behind try / except so that
# this file does not explode in minimal environments.
try:
    from confluent_kafka import Consumer, KafkaException, Message  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Consumer = None  # type: ignore
    KafkaException = Exception  # type: ignore
    Message = None  # type: ignore

try:
    import jsonschema  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    jsonschema = None  # type: ignore

try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # fallback stubs (metrics become no-ops)
    class _Dummy:  # pragma: no cover
        def __init__(self, *_, **__):
            pass

        def labels(self, *_, **__):
            return self

        def inc(self, *_):
            pass

        def set(self, *_):
            pass

        def observe(self, *_):
            pass

    Counter = Gauge = Histogram = _Dummy  # type: ignore

###############################################################################
# Logger setup
###############################################################################
logger = logging.getLogger("pulse_stream.module_21")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)
logger.addHandler(handler)

###############################################################################
# Prometheus metrics
###############################################################################
EVENTS_CONSUMED = Counter(
    "psn_events_consumed_total",
    "Total number of raw events consumed from Kafka",
    ["topic", "partition"],
)
EVENTS_VALID = Counter(
    "psn_events_valid_total",
    "Total number of events passing validation",
    ["topic"],
)
EVENTS_INVALID = Counter(
    "psn_events_invalid_total",
    "Total number of events failing validation",
    ["topic"],
)
EVENT_PROCESSING_LATENCY = Histogram(
    "psn_event_processing_latency_seconds",
    "End-to-end latency for processing a single event",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5),
)

###############################################################################
# Configuration
###############################################################################


@dataclass(frozen=True, slots=True)
class KafkaConfig:
    """
    Reduced Kafka configuration dataclass. In real projects this would be much
    more exhaustive or rely on `pydantic` for validation.
    """

    bootstrap_servers: str
    group_id: str
    topics: List[str]
    security_protocol: str = "PLAINTEXT"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    commit_interval: int = 5  # seconds
    # Additional producer configs could be added as required.


###############################################################################
# Strategy pattern for commit handling
###############################################################################


class CommitStrategy(ABC):
    """
    Strategy interface for committing offsets.

    Different deployments might have distinct semantics—automatic,
    batch-wise, or transactional.
    """

    @abstractmethod
    def maybe_commit(self, consumer: "Consumer") -> None:  # pragma: no cover
        """Commit offsets if appropriate for the strategy."""


class AutoCommitStrategy(CommitStrategy):
    """
    Let the underlying Kafka client handle everything automatically.
    """

    def maybe_commit(self, consumer: "Consumer") -> None:
        # When auto commit is True at client level, no manual intervention needed.
        logger.debug("AutoCommitStrategy: rely on Kafka auto commits.")


class PeriodicCommitStrategy(CommitStrategy):
    """
    Commit offsets every N seconds regardless of message count.
    """

    def __init__(self, interval: int = 5):
        self._interval = interval
        self._last_commit = time.monotonic()

    def maybe_commit(self, consumer: "Consumer") -> None:
        now = time.monotonic()
        if now - self._last_commit >= self._interval:
            logger.debug("PeriodicCommitStrategy: committing offsets to Kafka.")
            consumer.commit(asynchronous=False)
            self._last_commit = now


###############################################################################
# Validation
###############################################################################


@dataclass(slots=True)
class SchemaValidator:
    """
    Simple JSON-Schema validator wrapper.

    Uses `jsonschema` if available. Falls back to naive validation otherwise.
    """

    schema: Dict[str, object]

    def validate(self, payload: Dict[str, object], topic: str) -> bool:
        if jsonschema is None:
            # Fallback: ensure mandatory keys exist
            mandatory = {"id", "timestamp", "text"}
            if not mandatory.issubset(payload):
                EVENTS_INVALID.labels(topic=topic).inc()
                logger.debug("Validator: missing mandatory keys %s", mandatory - payload.keys())
                return False
            return True

        try:
            jsonschema.validate(payload, self.schema)  # type: ignore[attr-defined]
            return True
        except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
            EVENTS_INVALID.labels(topic=topic).inc()
            logger.debug("Validator: schema error %s", exc)
            return False


###############################################################################
# Transformation framework (Strategy Pattern again)
###############################################################################


@runtime_checkable
class EventTransformer(Protocol):
    @abstractmethod
    def transform(self, event: Dict[str, object]) -> Dict[str, object]:  # pragma: no cover
        """Apply transformation to an event dict."""


class SentimentTransformer:
    """
    Dummy sentiment transformer. In the full platform this would likely call a
    fine-tuned NLP model behind an async micro-service.
    """

    def transform(self, event: Dict[str, object]) -> Dict[str, object]:
        text: str = event.get("text", "")
        # Heuristic: positive if :) negatively if :(, else neutral
        if ":)" in text:
            sentiment = 0.9
        elif ":(" in text:
            sentiment = 0.1
        else:
            sentiment = 0.5
        event["sentiment_score"] = sentiment
        return event


class ToxicityTransformer:
    """
    Dummy toxicity detector. Replace with Perspective API or custom model.
    """

    def transform(self, event: Dict[str, object]) -> Dict[str, object]:
        text: str = event.get("text", "")
        toxins = {"hate", "kill", "stupid"}
        toxicity = 1.0 if any(tok in text.lower() for tok in toxins) else 0.0
        event["toxicity_score"] = toxicity
        return event


###############################################################################
# Observer pattern for downstream publications
###############################################################################


class EventObserver(Protocol):
    def update(self, event: Dict[str, object]) -> None:  # pragma: no cover
        ...


###############################################################################
# Consumer thread
###############################################################################


class ConsumerThread(threading.Thread):
    """
    Dedicated thread hosting the Kafka poll loop so that we can orchestrate
    clean shutdown via POSIX signals.
    """

    daemon = True

    def __init__(
        self,
        kafka_cfg: KafkaConfig,
        validator: SchemaValidator,
        transformers: Iterable[EventTransformer],
        observers: Iterable[EventObserver],
        commit_strategy: Optional[CommitStrategy] = None,
        poll_timeout: float = 1.0,
    ):
        super().__init__(name="psn-consumer-thread")
        if Consumer is None:
            raise RuntimeError("confluent-kafka is not installed. Install it to run this module.")

        self._kafka_cfg = kafka_cfg
        self._validator = validator
        self._transformers = list(transformers)
        self._observers = list(observers)
        self._commit_strategy = commit_strategy or AutoCommitStrategy()
        self._poll_timeout = poll_timeout
        self._stopped = threading.Event()
        self._msg_queue: "queue.Queue[Message]" = queue.Queue(maxsize=10_000)

        self._consumer: Consumer = Consumer(
            {
                "bootstrap.servers": kafka_cfg.bootstrap_servers,
                "group.id": kafka_cfg.group_id,
                "security.protocol": kafka_cfg.security_protocol,
                "auto.offset.reset": kafka_cfg.auto_offset_reset,
                "enable.auto.commit": kafka_cfg.enable_auto_commit,
            }
        )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def stop(self) -> None:
        logger.info("ConsumerThread: stop signal received.")
        self._stopped.set()

    # --------------------------------------------------------------------- #
    # Thread run method
    # --------------------------------------------------------------------- #

    def run(self) -> None:
        logger.info("ConsumerThread: subscribing to topics %s", self._kafka_cfg.topics)
        self._consumer.subscribe(self._kafka_cfg.topics)

        try:
            while not self._stopped.is_set():
                try:
                    msg: Optional[Message] = self._consumer.poll(self._poll_timeout)
                    if msg is None:
                        # periodic commit if we haven't received anything
                        self._commit_strategy.maybe_commit(self._consumer)
                        continue
                    if msg.error():  # pragma: no cover
                        raise KafkaException(msg.error())
                    self._process_msg(msg)
                except Exception as exc:  # pragma: no cover
                    logger.exception("ConsumerThread: Unhandled error in poll loop. %s", exc)
        finally:
            logger.info("ConsumerThread: closing Kafka consumer.")
            try:
                self._consumer.close()
            except Exception:  # pragma: no cover
                logger.exception("ConsumerThread: error on close.")

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _process_msg(self, msg: Message) -> None:
        start_time = time.monotonic()

        topic = msg.topic()
        partition = msg.partition()
        EVENTS_CONSUMED.labels(topic=topic, partition=partition).inc()

        try:
            payload = json.loads(msg.value().decode("utf-8"))
        except json.JSONDecodeError as exc:
            EVENTS_INVALID.labels(topic=topic).inc()
            logger.debug("ConsumerThread: JSON decode error %s", exc)
            return

        if not self._validator.validate(payload, topic):
            # invalid; nothing more to do
            return

        # apply transformations
        for transformer in self._transformers:
            try:
                payload = transformer.transform(payload)
            except Exception as exc:  # pragma: no cover
                logger.exception("Transformer %s failed: %s", transformer.__class__.__name__, exc)

        # notify observers
        for observer in self._observers:
            try:
                observer.update(payload)
            except Exception as exc:  # pragma: no cover
                logger.exception("Observer %s failed: %s", observer.__class__.__name__, exc)

        duration = time.monotonic() - start_time
        EVENTS_VALID.labels(topic=topic).inc()
        EVENT_PROCESSING_LATENCY.observe(duration)

        # commit offsets as per strategy
        self._commit_strategy.maybe_commit(self._consumer)


###############################################################################
# Example observer implementation
###############################################################################


class StdoutObserver:
    """
    Very simple observer that dumps transformed events to stdout.

    Useful for smoke-testing the pipeline in isolation.
    """

    def update(self, event: Dict[str, object]) -> None:
        print(json.dumps(event, ensure_ascii=False), flush=True)


###############################################################################
# Graceful shutdown utils
###############################################################################


def _install_signal_handlers(worker: ConsumerThread) -> None:
    """
    Register SIGINT / SIGTERM so that docker / k8s / systemd can
    coordinate a polite shutdown.
    """

    def _handler(signum: int, frame: Optional[FrameType]) -> None:  # pragma: no cover
        logger.info("Signal %s received, requesting shutdown.", signum)
        worker.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


###############################################################################
# Entry point helper (optional)
###############################################################################


def main(argv: Optional[List[str]] = None) -> None:
    """
    A lightweight CLI when this module is executed as a script.

    Example:
        $ python -m src.module_21 --bootstrap localhost:9092 --group demo --topics tweets
    """
    import argparse

    parser = argparse.ArgumentParser(description="PulseStream Nexus streaming consumer (demo)")
    parser.add_argument("--bootstrap", required=True, help="Kafka bootstrap servers.")
    parser.add_argument("--group", default="psn-demo-consumer", help="Consumer group id.")
    parser.add_argument(
        "--topics", required=True, help="Comma-separated list of Kafka topics to consume."
    )
    parser.add_argument("--commit-interval", type=int, default=5, help="Commit interval in seconds")
    parser.add_argument(
        "--verbose", action="store_true", help="Enable DEBUG logging for troubleshooting."
    )

    args = parser.parse_args(argv)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    kafka_cfg = KafkaConfig(
        bootstrap_servers=args.bootstrap,
        group_id=args.group,
        topics=args.topics.split(","),
        commit_interval=args.commit_interval,
    )

    validator = SchemaValidator(schema=_MINIMAL_SCHEMA)
    transformers = [SentimentTransformer(), ToxicityTransformer()]
    observers = [StdoutObserver()]
    commit_strategy = PeriodicCommitStrategy(interval=kafka_cfg.commit_interval)

    consumer_thread = ConsumerThread(
        kafka_cfg=kafka_cfg,
        validator=validator,
        transformers=transformers,
        observers=observers,
        commit_strategy=commit_strategy,
    )
    _install_signal_handlers(consumer_thread)
    consumer_thread.start()

    # Keep the main thread alive to handle signals
    while consumer_thread.is_alive():
        time.sleep(0.5)

    logger.info("Main thread exiting.")


###############################################################################
# Minimal schema definition
###############################################################################

_MINIMAL_SCHEMA: Dict[str, object] = {
    "type": "object",
    "required": ["id", "timestamp", "text"],
    "properties": {
        "id": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"},
        "text": {"type": "string"},
        # Additional optional fields
    },
    "additionalProperties": True,
}

###############################################################################
# Module exports
###############################################################################

__all__ = [
    "KafkaConfig",
    "SchemaValidator",
    "SentimentTransformer",
    "ToxicityTransformer",
    "StdoutObserver",
    "ConsumerThread",
    "PeriodicCommitStrategy",
    "AutoCommitStrategy",
    "main",
]


# ---------------------------------------------------------------------------- #
# When executed directly
# ---------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
```