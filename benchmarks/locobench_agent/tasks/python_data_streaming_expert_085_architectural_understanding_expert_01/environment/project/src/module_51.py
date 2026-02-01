```python
"""
PulseStream Nexus
=================
module_51.py
------------

High-throughput Kafka consumer with pluggable validation & transformation
strategies plus Prometheus telemetry.

This module demonstrates Clean-Architecture friendly, production-grade code that
lives in the *interface adapters* layer.  It owns *no* business logic; rather,
it coordinates I/O concerns (Kafka, Prometheus, Great Expectations, etc.) and
delegates to use-case agnostic `Strategy` and `Observer` abstractions.

Author  : PulseStream Engineering
License : MIT (see repository root)
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from multiprocessing import Event
from threading import Thread
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable

# kafka-python driver —— will raise ImportError in unit tests without Kafka.
try:
    from confluent_kafka import Consumer, KafkaException, Message, TopicPartition
except ImportError:  # pragma: no cover
    # Provide a minimal dummy shim so static type checkers stay happy.
    Consumer = object  # type: ignore  # noqa: N816
    KafkaException = Exception  # type: ignore
    Message = object  # type: ignore
    TopicPartition = object  # type: ignore

# Metrics — fall back to no-op if library absent (e.g., during CI).
try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
except ImportError:  # pragma: no cover
    class _NoOp:
        def __getattr__(self, name):  # noqa: D401
            return self

        def __call__(self, *_: Any, **__: Any) -> "_NoOp":  # noqa: D401
            return self

        # Metrics API
        def inc(self, *_: Any, **__: Any) -> None: ...
        def observe(self, *_: Any, **__: Any) -> None: ...
        def set(self, *_: Any, **__: Any) -> None: ...

    Counter = Histogram = Gauge = _NoOp  # type: ignore # noqa: N816
    def start_http_server(*_: Any, **__: Any) -> None: ...  # noqa: D401


# ------------------------------------------------------------
# Configuration dataclasses
# ------------------------------------------------------------

@dataclass(frozen=True)
class KafkaConsumerConfig:
    """
    Runtime configuration for the Kafka consumer.

    Notes
    -----
    * The config is immutable (`frozen=True`) to encourage declarative design.
    """
    bootstrap_servers: str
    group_id: str
    topics: List[str]
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    max_poll_records: int = 500
    session_timeout_ms: int = 10_000
    extra_config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricsConfig:
    """
    Prometheus metrics exporter settings.
    """
    port: int = 9102
    addr: str = "0.0.0.0"


# ------------------------------------------------------------
# Strategy & Observer Protocols
# ------------------------------------------------------------

@runtime_checkable
class ValidationStrategy(Protocol):
    """
    Validate individual events.

    Returning `True` admits the record to downstream processing;
    returning `False` drops the record silently.

    Raising an exception results in the record being *nacked*.
    """

    def validate(self, payload: Dict[str, Any]) -> bool:  # noqa: D401
        ...


@runtime_checkable
class TransformationStrategy(Protocol):
    """
    Transform records in place or return a mutated copy.
    """

    def transform(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D401
        ...


@runtime_checkable
class EventObserver(Protocol):
    """
    Observer contract for downstream consumers (e.g., use-case interactors,
    message buses, or test probes).
    """

    def update(self, event: Dict[str, Any]) -> None:  # noqa: D401
        ...


# ------------------------------------------------------------
# Default strategy implementations
# ------------------------------------------------------------

class JSONSchemaValidation(ValidationStrategy):
    """
    Stub JSON-schema validator.

    A production implementation would pull schema definitions from a registry
    such as Confluent SR or AWS Glue.  Here we just sanity-check a few fields.
    """

    REQUIRED_FIELDS = {"id", "author", "body", "timestamp"}

    def validate(self, payload: Dict[str, Any]) -> bool:
        missing = self.REQUIRED_FIELDS.difference(payload)
        if missing:
            raise ValueError(f"Schema validation failed, missing: {missing}")
        return True


class NoopTransformation(TransformationStrategy):
    """
    Pass-through strategy for benchmarks or smoke tests.
    """

    def transform(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload


# ------------------------------------------------------------
# Prometheus metric handles
# ------------------------------------------------------------

KAFKA_MSGS_CONSUMED = Counter(
    "psn_kafka_msgs_consumed_total",
    "Total Kafka messages consumed",
    ["topic"],
)

KAFKA_MSGS_VALID = Counter(
    "psn_kafka_msgs_validated_total",
    "Messages that passed validation",
    ["topic"],
)

KAFKA_MSGS_INVALID = Counter(
    "psn_kafka_msgs_invalid_total",
    "Messages that failed validation",
    ["topic"],
)

KAFKA_MSG_LAG = Gauge(
    "psn_kafka_consumer_lag",
    "Consumer lag (difference between end offset and current position)",
    ["topic", "partition"],
)

KAFKA_CONSUME_LATENCY = Histogram(
    "psn_kafka_consume_latency_seconds",
    "Time spent between poll and observer update",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 1, 5),
)


# ------------------------------------------------------------
# Core consumer
# ------------------------------------------------------------

class GracefulKiller:
    """
    Captures SIGINT/SIGTERM so the consumer can shut down without data loss.
    """

    def __init__(self) -> None:
        self._kill_now = Event()
        signal.signal(signal.SIGINT, self._exit_gracefully)   # Ctrl+C
        signal.signal(signal.SIGTERM, self._exit_gracefully)  # Docker stop

    def _exit_gracefully(self, *_: Any) -> None:
        logging.warning("Shutdown signal received. Commencing graceful stop…")
        self._kill_now.set()

    @property
    def killed(self) -> bool:  # noqa: D401
        return self._kill_now.is_set()


class StreamConsumer(Thread):
    """
    High-volume Kafka consumer with validation, transformation, and observer
    notification pipeline.

    The consumer is executed in its own thread to avoid blocking the caller
    (e.g., an API process).
    """

    daemon = True

    def __init__(
        self,
        cfg: KafkaConsumerConfig,
        validator: ValidationStrategy,
        transformer: TransformationStrategy,
        observers: Iterable[EventObserver] | None = None,
        metrics_cfg: MetricsConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(name="StreamConsumer")
        self.cfg = cfg
        self.validator = validator
        self.transformer = transformer
        self.observers: List[EventObserver] = list(observers or [])
        self._killer = GracefulKiller()
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        # instantiate metrics HTTP exporter if config supplied
        if metrics_cfg:
            start_http_server(metrics_cfg.port, metrics_cfg.addr)
            self.logger.info("Prometheus exporter listening on %s:%s",
                             metrics_cfg.addr, metrics_cfg.port)

        # Compose confluent_kafka parameters
        kafka_conf: Dict[str, Any] = {
            "bootstrap.servers": cfg.bootstrap_servers,
            "group.id": cfg.group_id,
            "enable.auto.commit": cfg.enable_auto_commit,
            "auto.offset.reset": cfg.auto_offset_reset,
            "session.timeout.ms": cfg.session_timeout_ms,
        }
        kafka_conf.update(cfg.extra_config)

        self._consumer: Consumer = Consumer(kafka_conf)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def register_observer(self, observer: EventObserver) -> None:
        self.observers.append(observer)

    def run(self) -> None:  # noqa: D401
        """
        Core polling loop.  Will shut down gracefully on SIGTERM/INT.
        """
        self._subscribe()

        self.logger.info(
            "Consumer started | topics=%s | group_id=%s",
            self.cfg.topics,
            self.cfg.group_id,
        )

        while not self._killer.killed:
            try:
                with self._time_consume_latency(self.cfg.topics[0]):
                    msg: Optional[Message] = self._consumer.poll(0.5)
                    if msg is None:
                        continue
                    if msg.error():
                        raise KafkaException(msg.error())

                    topic = msg.topic()
                    payload = self._parse(msg.value())
                    KAFKA_MSGS_CONSUMED.labels(topic=topic).inc()

                    try:
                        if self.validator.validate(payload):
                            KAFKA_MSGS_VALID.labels(topic=topic).inc()
                            transformed = self.transformer.transform(payload)
                            self._notify_observers(transformed)
                    except Exception as exc:  # noqa: BLE001
                        # Handle malformed messages without crashing loop.
                        KAFKA_MSGS_INVALID.labels(topic=topic).inc()
                        self.logger.warning("Validation failed: %s", exc, exc_info=False)
                        # Optionally send to DLQ / Sentry here.
                        continue

                # Manual commit after successful processing to avoid duplicates.
                if not self.cfg.enable_auto_commit:
                    self._consumer.commit(asynchronous=False)
                self._record_lag(msg)

            except Exception as fatal:  # noqa: BLE001
                self.logger.exception("Fatal error in consumer loop: %s", fatal)
                time.sleep(1)  # backoff before retry
        # Close routine
        self._shutdown()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _subscribe(self) -> None:
        self._consumer.subscribe(self.cfg.topics)
        self.logger.debug("Subscribed to %s", self.cfg.topics)

    def _parse(self, raw_bytes: bytes) -> Dict[str, Any]:
        try:
            return json.loads(raw_bytes)
        except json.JSONDecodeError as e:  # noqa: B904
            raise ValueError(f"Invalid JSON payload: {e}") from e

    def _notify_observers(self, event: Dict[str, Any]) -> None:
        for observer in self.observers:
            try:
                observer.update(event)
            except Exception:  # pragma: no cover  # noqa: BLE001
                self.logger.exception("Observer %s failed", observer.__class__.__name__)

    def _record_lag(self, msg: Message) -> None:  # noqa: D401
        """
        For each partition, compute latest offset minus the current offset.
        """
        try:
            tp = TopicPartition(msg.topic(), msg.partition())
            low, high = self._consumer.get_watermark_offsets(tp, cached=True)
            lag = high - msg.offset() - 1  # offsets are zero-based
            KAFKA_MSG_LAG.labels(topic=msg.topic(), partition=msg.partition()).set(lag)
        except Exception:  # noqa: BLE001
            # Don't crash metrics on broker hiccup.
            self.logger.debug("Lag computation failed", exc_info=False)

    @contextmanager
    def _time_consume_latency(self, topic: str):  # noqa: D401
        """
        Histogram context.
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start_time
            KAFKA_CONSUME_LATENCY.labels(topic=topic).observe(elapsed)

    def _shutdown(self) -> None:
        self.logger.info("Stopping consumer; committing final offsets…")
        try:
            self._consumer.commit(asynchronous=False)
        except Exception:  # noqa: BLE001
            self.logger.warning("Offset commit during shutdown failed", exc_info=False)
        finally:
            self._consumer.close()
        self.logger.info("Consumer stopped.")


# ------------------------------------------------------------
# Example observer for demonstration / unit testing
# ------------------------------------------------------------

class PrintObserver(EventObserver):
    """
    Light-weight observer that pretty-prints events to STDOUT.

    Ideally, downstream adapters (e.g., a REST API or ML sink) would implement
    this protocol instead.
    """

    def update(self, event: Dict[str, Any]) -> None:  # noqa: D401
        print(f"[{event.get('timestamp', '--')}] "
              f"{event.get('author', 'anon')}: {event.get('body', '')[:80]}")


# ------------------------------------------------------------
# Bootstrap entry-point (optional)
# ------------------------------------------------------------

def main() -> None:  # pragma: no cover
    """
    Basic standalone runner useful for local development with `docker compose`.

    Example
    -------
    $ python -m src.module_51 \\
        --brokers localhost:29092 \\
        --topics twitter_stream
    """
    import argparse

    parser = argparse.ArgumentParser(description="PulseStream Nexus ‑ Kafka ingest")
    parser.add_argument("--brokers", required=True, help="Kafka bootstrap servers")
    parser.add_argument("--topics", required=True, nargs="+", help="Topic list")
    parser.add_argument("--group", default="psn_ingest", help="Consumer group id")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )

    consumer_cfg = KafkaConsumerConfig(
        bootstrap_servers=args.brokers,
        group_id=args.group,
        topics=args.topics,
    )

    consumer = StreamConsumer(
        cfg=consumer_cfg,
        validator=JSONSchemaValidation(),
        transformer=NoopTransformation(),
        observers=[PrintObserver()],
        metrics_cfg=MetricsConfig(),
    )
    consumer.start()
    consumer.join()  # Wait forever


if __name__ == "__main__":  # pragma: no cover
    main()
```