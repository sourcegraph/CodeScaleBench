```python
"""
src/module_19.py

PulseStream Nexus – Data-Streaming Ingestion & Validation

This module implements a resilient, observable Kafka ingestion loop that
validates, enriches, and forwards social-network events into the internal
event bus.  It purposely contains no framework or I/O specific business rules,
conforming to PulseStream’s Clean-Architecture guideline.

Key patterns used
-----------------
Pipeline Pattern      – staged ETL processing
Observer Pattern      – decoupled progress / error notifications
Strategy Pattern      – pluggable record transforms (sentiment, toxicity, …)

The module can be executed as a standalone CLI as well as imported as a library.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Type

# --------------------------------------------------------------------------- #
# Optional, external dependencies                                             #
# --------------------------------------------------------------------------- #

try:  # pragma: no cover
    from confluent_kafka import Consumer, KafkaError, Message  # type: ignore
except ModuleNotFoundError:  # graceful degradation for environments w/o C libs
    KafkaError = Exception

    class Message:  # noqa: D401
        """Poor-man Kafka message stand-in."""

        def __init__(self, value: bytes, key: Optional[bytes] = None) -> None:
            self._value = value
            self._key = key

        def value(self) -> bytes:  # noqa: D401
            return self._value

        def key(self) -> Optional[bytes]:  # noqa: D401
            return self._key

        def error(self) -> None:  # noqa: D401
            return None

    class Consumer:  # noqa: D401
        """Very small subset of confluent_kafka.Consumer API."""

        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def subscribe(self, _topics: List[str]) -> None:
            pass

        def poll(self, _timeout: float) -> Optional[Message]:
            time.sleep(_timeout)
            return None  # noop

        def close(self) -> None:
            pass


try:  # pragma: no cover
    from prometheus_client import Counter, Histogram, start_http_server  # type: ignore
except ModuleNotFoundError:  # fallback to no-op metrics
    logging.warning("prometheus_client not found – metrics disabled.")

    class _Metric:  # noqa: D401
        def inc(self, *_a: Any, **_kw: Any) -> None:
            pass

        def observe(self, *_a: Any, **_kw: Any) -> None:
            pass

    def Counter(*_a: Any, **_kw: Any) -> _Metric:  # type: ignore
        return _Metric()

    def Histogram(*_a: Any, **_kw: Any) -> _Metric:  # type: ignore
        return _Metric()

    def start_http_server(*_a: Any, **_kw: Any) -> None:  # type: ignore
        pass


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class IngestionConfig:
    """
    Immutable runtime configuration for the ingestion service.

    Values are primarily taken from environment variables to streamline cloud
    deployments but can be instantiated programmatically in tests as well.
    """

    kafka_bootstrap: str = field(
        default_factory=lambda: os.getenv("PSN_KAFKA_BOOTSTRAP", "localhost:9092")
    )
    kafka_topic: str = field(
        default_factory=lambda: os.getenv("PSN_KAFKA_TOPIC", "social-events")
    )
    kafka_group_id: str = field(
        default_factory=lambda: os.getenv("PSN_KAFKA_GROUP", "psn-ingestor")
    )
    validation_expectation_suite: str = field(
        default_factory=lambda: os.getenv(
            "PSN_VALIDATION_SUITE", "expectation_suites/social_events.json"
        )
    )
    prometheus_port: int = field(
        default_factory=lambda: int(os.getenv("PSN_PROM_PORT", "9191"))
    )
    batch_size: int = field(default_factory=lambda: int(os.getenv("PSN_BATCH", "512")))
    poll_timeout: float = field(
        default_factory=lambda: float(os.getenv("PSN_POLL_TIMEOUT", "0.2"))
    )


# --------------------------------------------------------------------------- #
# Domain entities / value objects                                             #
# --------------------------------------------------------------------------- #

class EventRecord(Dict[str, Any]):
    """Typing alias for a normalised social-event document."""


# --------------------------------------------------------------------------- #
# Strategy Pattern – transformations                                          #
# --------------------------------------------------------------------------- #

class RecordTransformer(Protocol):
    """
    Strategy interface for record transformations.

    Implementations must be stateless and thread-safe.
    """

    def transform(self, record: EventRecord) -> EventRecord:  # noqa: D401
        ...


class SentimentTransformer:
    """Adds a naive sentiment score placeholder."""

    def transform(self, record: EventRecord) -> EventRecord:  # noqa: D401
        text: str = record.get("text", "")
        record["sentiment_score"] = (
            1 if "love" in text.lower() else -1 if "hate" in text.lower() else 0
        )
        return record


class ToxicityTransformer:
    """Very simple keyword-based toxicity flag."""

    _toxic_keywords: List[str] = ["idiot", "moron", "stupid"]

    def transform(self, record: EventRecord) -> EventRecord:  # noqa: D401
        text: str = record.get("text", "").lower()
        record["toxic"] = any(w in text for w in self._toxic_keywords)
        return record


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #

class RecordValidationError(RuntimeError):
    """Raised when a record fails the expectation suite."""


class RecordValidator:
    """
    Lightweight Great-Expectations wrapper.

    The actual GE dependency is optional – if not available we fall back to a
    JSON schema defined by the provided expectation suite file.
    """

    def __init__(self, suite_path: str) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._rules = self._load_suite(suite_path)

    @staticmethod
    def _load_suite(path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Expectation suite not found: {path}")
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)

    def validate(self, record: EventRecord) -> None:
        """
        Perform very simple validation against the JSON-defined rules.

        The schema might look like:
        {
          "required": ["id", "text", "source"],
          "properties": {
              "id": {"type": "string"},
              "text": {"type": "string"},
              "source": {"enum": ["twitter", "reddit", "mastodon", "discord"]}
          }
        }
        """
        required = set(self._rules.get("required", []))
        missing = required - record.keys()
        if missing:
            raise RecordValidationError(f"Missing fields: {sorted(missing)}")

        props = self._rules.get("properties", {})
        for key, rule in props.items():
            if key not in record:
                continue
            value = record[key]
            if "enum" in rule and value not in rule["enum"]:
                raise RecordValidationError(f"Invalid value for {key}: {value!r}")
            if rule.get("type") == "string" and not isinstance(value, str):
                raise RecordValidationError(
                    f"Expected string for {key}, got {type(value).__name__}"
                )


# --------------------------------------------------------------------------- #
# Observer Pattern – event bus                                                #
# --------------------------------------------------------------------------- #

class EventSubscriber(Protocol):
    """
    Observer interface for subscribers that receive processed records or errors.
    """

    def on_success(self, record: EventRecord) -> None:  # noqa: D401
        ...

    def on_error(self, err: Exception, raw: bytes | None = None) -> None:  # noqa: D401
        ...


class EventPublisher:
    """Thread-safe, fan-out publisher."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: List[EventSubscriber] = []

    def subscribe(self, sub: EventSubscriber) -> None:
        with self._lock:
            self._subs.append(sub)

    def publish_success(self, record: EventRecord) -> None:
        for sub in self._subs:
            try:
                sub.on_success(record)
            except Exception:  # pragma: no cover
                logging.exception("Subscriber failed on_success")

    def publish_error(self, err: Exception, raw: bytes | None = None) -> None:
        for sub in self._subs:
            try:
                sub.on_error(err, raw)
            except Exception:  # pragma: no cover
                logging.exception("Subscriber failed on_error")


# --------------------------------------------------------------------------- #
# Metrics                                                                     #
# --------------------------------------------------------------------------- #

_ingested_counter = Counter(
    "psn_records_ingested_total",
    "Total number of Kafka records ingested",
    ["outcome"],
)
_ingest_latency = Histogram(
    "psn_record_ingest_latency_seconds", "Latency between poll and processing"
)


# --------------------------------------------------------------------------- #
# Ingestion pipeline                                                          #
# --------------------------------------------------------------------------- #

@dataclass
class _TransformPipeline:
    """
    Pipeline consisting of a validator followed by an ordered list of
    RecordTransformers.
    """

    validator: RecordValidator
    transforms: List[RecordTransformer]

    def process(self, record: EventRecord) -> EventRecord:
        self.validator.validate(record)
        for tf in self.transforms:
            record = tf.transform(record)
        return record


class StreamIngestor:
    """
    Near-real-time ingestion loop.

    Usage
    -----
    >>> cfg = IngestionConfig()
    >>> ingestor = StreamIngestor(cfg)
    >>> ingestor.start()
    """

    _shutdown_flag = threading.Event()

    def __init__(
        self,
        cfg: IngestionConfig,
        transformers: Optional[Iterable[RecordTransformer]] = None,
        publisher: Optional[EventPublisher] = None,
        consumer_factory: Callable[[IngestionConfig], Consumer]
        | None = None,
    ) -> None:
        self.cfg = cfg
        self.logger = logging.getLogger(self.__class__.__name__)
        self.publisher = publisher or EventPublisher()
        self.transform_pipeline = _TransformPipeline(
            validator=RecordValidator(cfg.validation_expectation_suite),
            transforms=list(transformers or (SentimentTransformer(), ToxicityTransformer())),
        )
        self.consumer = (consumer_factory or self._default_consumer_factory)(cfg)

    # --------------------------------------------------------------------- #
    # Lifecycle                                                              #
    # --------------------------------------------------------------------- #

    def start(self) -> None:  # blocking
        self.logger.info(
            "Starting StreamIngestor (topic=%s, group=%s) …",
            self.cfg.kafka_topic,
            self.cfg.kafka_group_id,
        )
        start_http_server(self.cfg.prometheus_port)
        self.consumer.subscribe([self.cfg.kafka_topic])

        signal.signal(signal.SIGINT, self._signal_handler)   # graceful CTRL-C
        signal.signal(signal.SIGTERM, self._signal_handler)  # k8s termination

        try:
            while not self._shutdown_flag.is_set():
                t0 = time.perf_counter()
                msg = self.consumer.poll(self.cfg.poll_timeout)
                elapsed = time.perf_counter() - t0
                if msg is None:
                    continue
                _ingest_latency.observe(elapsed)
                if msg.error():
                    self._handle_error(RuntimeError(str(msg.error())), raw=None)
                    continue
                self._handle_message(msg)
        finally:
            self._cleanup()

    def stop(self) -> None:
        """Can be called from outside to shut down the loop."""
        self._shutdown_flag.set()

    # --------------------------------------------------------------------- #
    # Internal helpers                                                       #
    # --------------------------------------------------------------------- #

    def _default_consumer_factory(self, cfg: IngestionConfig) -> Consumer:
        return Consumer(
            {
                "bootstrap.servers": cfg.kafka_bootstrap,
                "group.id": cfg.kafka_group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": True,
            }
        )

    def _signal_handler(self, *_a: Any) -> None:
        self.logger.info("Signal received – shutting down …")
        self.stop()

    def _handle_message(self, msg: Message) -> None:
        raw: bytes = msg.value()
        try:
            record = json.loads(raw.decode("utf-8"))
            record["ingested_at"] = datetime.now(timezone.utc).isoformat()
            record = self.transform_pipeline.process(record)
        except Exception as err:  # capture both JSON and validation errors
            self._handle_error(err, raw=raw)
            return

        _ingested_counter.labels(outcome="success").inc()
        self.publisher.publish_success(record)
        self.logger.debug("Record processed: %s", record.get("id", "<no-id>"))

    def _handle_error(self, err: Exception, raw: bytes | None) -> None:
        _ingested_counter.labels(outcome="error").inc()
        self.publisher.publish_error(err, raw)
        self.logger.warning("Failed record: %s", err, exc_info=self.logger.isEnabledFor(logging.DEBUG))

    def _cleanup(self) -> None:
        self.consumer.close()
        self.logger.info("StreamIngestor stopped.")

    # --------------------------------------------------------------------- #
    # Context-manager sugar                                                  #
    # --------------------------------------------------------------------- #

    def __enter__(self) -> "StreamIngestor":
        threading.Thread(target=self.start, daemon=True).start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: TracebackType | None,
    ) -> bool:
        self.stop()
        return False  # don’t suppress exceptions


# --------------------------------------------------------------------------- #
# Example subscriber                                                          #
# --------------------------------------------------------------------------- #

class StdoutSubscriber:
    """Very simple subscriber that prints processed records to stdout."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def on_success(self, record: EventRecord) -> None:  # noqa: D401
        with self._lock:
            print(json.dumps(record, ensure_ascii=False))

    def on_error(self, err: Exception, raw: bytes | None = None) -> None:  # noqa: D401
        with self._lock:
            print(f"ERROR: {err}", file=sys.stderr)
            if raw is not None:
                print(f"RAW: {raw!r}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# CLI entry point                                                             #
# --------------------------------------------------------------------------- #

def _setup_logging() -> None:
    level = os.getenv("PSN_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main() -> None:  # pragma: no cover
    """
    Minimal CLI that runs the ingestor with a StdoutSubscriber.
    """
    _setup_logging()
    cfg = IngestionConfig()
    ingestor = StreamIngestor(cfg)
    ingestor.publisher.subscribe(StdoutSubscriber())
    ingestor.start()


if __name__ == "__main__":  # pragma: no cover
    main()
```