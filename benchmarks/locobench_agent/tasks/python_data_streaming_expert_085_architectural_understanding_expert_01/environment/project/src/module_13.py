```python
"""
PulseStream Nexus – Module 13
=============================

Real-time Sentiment/Toxicity Enrichment Pipeline Stage
-----------------------------------------------------
This module implements a production-grade, pluggable sentiment (or toxicity)
enrichment stage for social-media messages flowing through PulseStream Nexus.

Key characteristics
-------------------
1. Strategy Pattern – interchangeable NLP back-ends
2. Observer Pattern  – decoupled side-effects (logging, metrics, APM, …)
3. Clean Architecture – no framework details leak into business logic
4. Operational grade – retry, back-pressure, instrumentation, validation

External dependencies (optional but recommended)
------------------------------------------------
kafka-python      – streaming I/O
textblob          – lightweight sentiment analysis
transformers      – advanced sentiment models (huggingface)
great_expectations– schema validation
prometheus_client – runtime metrics
tenacity          – retry policies

All heavy dependencies are lazily imported; a graceful fallback is employed
when a library is absent, so that the platform can decide which extras to
install at deployment time.

Author: PulseStream Nexus Core Team
License: Apache-2.0
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

# --------------------------------------------------------------------------- #
# Optional, heavyweight imports – guarded to keep cold-start fast and minimal  #
# --------------------------------------------------------------------------- #
try:
    from kafka import KafkaConsumer, KafkaProducer
except ModuleNotFoundError:  # pragma: no cover
    KafkaConsumer = KafkaProducer = None  # type: ignore

try:
    from textblob import TextBlob
except ModuleNotFoundError:  # pragma: no cover
    TextBlob = None  # type: ignore

try:
    import transformers  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    transformers = None  # type: ignore

try:
    import great_expectations as ge
except ModuleNotFoundError:  # pragma: no cover
    ge = None  # type: ignore

try:
    from prometheus_client import Counter, Histogram, start_http_server
except ModuleNotFoundError:  # pragma: no cover
    Counter = Histogram = start_http_server = None  # type: ignore

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ModuleNotFoundError:  # pragma: no cover
    # Fallback shim
    def retry(*dargs, **dkw):  # type: ignore
        def wrapper(fn):
            return fn

        return wrapper

    def stop_after_attempt(_):
        pass

    def wait_exponential(**_):
        pass


# ----------------------------- Config & Constants -------------------------- #


@dataclass(frozen=True)
class Settings:
    """Runtime configuration decoded from environment variables."""
    kafka_bootstrap_servers: str = field(
        default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    )
    inbound_topic: str = field(default_factory=lambda: os.getenv("RAW_TOPIC", "psn.raw"))
    outbound_topic: str = field(default_factory=lambda: os.getenv("ENRICHED_TOPIC", "psn.enriched"))
    group_id: str = field(default_factory=lambda: os.getenv("CONSUMER_GROUP", "psn.sentiment"))
    max_batch_size: int = field(default_factory=lambda: int(os.getenv("MAX_BATCH", "256")))
    prometheus_port: int = field(default_factory=lambda: int(os.getenv("PROM_PORT", "8000")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def __post_init__(self):
        logging.basicConfig(
            level=self.log_level,
            format="%(asctime)s.%(msecs)03dZ %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )


SETTINGS = Settings()


# ---------------------------- Domain Entities ------------------------------ #


@dataclass
class SocialEvent:
    """
    Canonical representation of a social-media message inside PulseStream Nexus.
    The schema is kept intentionally light; additional keys are captured inside
    `extra` to future-proof the event.
    """
    event_id: str
    user_id: str
    text: str
    source: str  # e.g. "twitter", "reddit"
    created_at: datetime
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SocialEvent":
        # Basic coercion & validation (extended validation handled by GE)
        return cls(
            event_id=str(payload["event_id"]),
            user_id=str(payload["user_id"]),
            text=str(payload["text"]),
            source=str(payload.get("source", "unknown")),
            created_at=datetime.fromisoformat(payload["created_at"]),
            extra={k: v for k, v in payload.items() if k not in {"event_id", "user_id", "text", "source", "created_at"}},
        )

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "event_id": self.event_id,
            "user_id": self.user_id,
            "text": self.text,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
        }
        data.update(self.extra)
        return data


# ------------------------ Validation (Great Expectations) ------------------ #


class SchemaValidator:
    """
    Wrap Great Expectations to validate inbound payloads.
    Falls back to a no-op validator when GE is unavailable.
    """

    def __init__(self) -> None:
        self._enabled = ge is not None
        if self._enabled:
            self._context = ge.get_context()
            self._expectation_suite = self._build_suite()

    @staticmethod
    def _build_suite():  # pragma: no cover
        """Dynamically create an expectation suite (simplified)."""
        suite = ge.core.ExpectationSuite("social_event_suite")
        suite.add_expectation(
            ge.expectations.core.ExpectColumnValuesToNotBeNullExpectation,
            kwargs={"column": "event_id"},
        )
        suite.add_expectation(
            ge.expectations.core.ExpectColumnValuesToNotBeNullExpectation,
            kwargs={"column": "text"},
        )
        suite.add_expectation(
            ge.expectations.core.ExpectColumnValuesToNotBeNullExpectation,
            kwargs={"column": "created_at"},
        )
        return suite

    def validate(self, payload: Dict[str, Any]) -> bool:
        if not self._enabled:
            return True
        batch = self._context.datasource.from_dict({"payload": payload})
        result = self._context.validate(batch, expectation_suite=self._expectation_suite)
        return result.success


# -------------------------- Strategy Pattern (NLP) ------------------------- #


class SentimentResult(Protocol):
    score: float
    label: str


class SentimentStrategy(ABC):
    """Abstract sentiment/tonality analysis strategy."""

    name: str

    @abstractmethod
    def analyze(self, text: str) -> SentimentResult:
        raise NotImplementedError


@dataclass
class TextBlobSentiment(SentimentResult):
    score: float
    label: str


class TextBlobStrategy(SentimentStrategy):
    """
    Lightweight sentiment analysis backed by TextBlob.
    Suitable for dev- and low-throughput envs.
    """

    name = "textblob"

    def __init__(self) -> None:
        if TextBlob is None:
            raise RuntimeError(
                "TextBlob library not available. "
                "Install with `pip install textblob` or choose a different strategy."
            )

    def analyze(self, text: str) -> TextBlobSentiment:
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity
        label = (
            "positive"
            if polarity > 0.2
            else "negative" if polarity < -0.2 else "neutral"
        )
        return TextBlobSentiment(score=polarity, label=label)


class DummyStrategy(SentimentStrategy):
    """
    Fallback when no external NLP libraries are installed.
    Performs a cheesy heuristic on happy/sad emoticons.
    """

    name = "dummy"

    def analyze(self, text: str) -> SentimentResult:
        lowered = text.lower()
        score = (":)" in lowered) - (":(" in lowered)
        label = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        return TextBlobSentiment(score=float(score), label=label)


STRATEGY_REGISTRY: Dict[str, type[SentimentStrategy]] = {
    "textblob": TextBlobStrategy,
    "dummy": DummyStrategy,
}

DEFAULT_STRATEGY = "textblob" if TextBlob is not None else "dummy"


# ----------------------------- Observer Pattern ---------------------------- #


class Observer(Protocol):
    def notify(self, event: SocialEvent, result: SentimentResult) -> None:
        ...


class LoggingObserver(Observer):
    def __init__(self) -> None:
        self._log = logging.getLogger("SentimentLogger")

    def notify(self, event: SocialEvent, result: SentimentResult) -> None:
        self._log.debug(
            "Processed event_id=%s score=%.3f label=%s",
            event.event_id,
            result.score,
            result.label,
        )


class MetricsObserver(Observer):
    """
    Prometheus metrics exporter. Lazily starts its HTTP server on first use.
    """

    def __init__(self, port: int = SETTINGS.prometheus_port) -> None:
        self._enabled = Counter is not None
        if not self._enabled:
            return

        # Start Prometheus exposition server only once
        _startup_guard = getattr(MetricsObserver, "_started", False)
        if not _startup_guard:
            start_http_server(port)
            MetricsObserver._started = True  # type: ignore

        # Metric primitives
        self._total = Counter(
            "psn_sentiment_total",
            "Total events processed by the sentiment module",
            ["label"],
        )
        self._latency = Histogram(
            "psn_sentiment_latency_seconds",
            "Time spent processing a single event",
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 5),
        )

    def notify(self, event: SocialEvent, result: SentimentResult) -> None:
        if not self._enabled:
            return
        self._total.labels(label=result.label).inc()


# ---------------------------- Core Processor ------------------------------- #


class GracefulKiller:
    """
    Helper that turns SIGINT/SIGTERM into a cooperative shutdown Event.
    """

    def __init__(self) -> None:
        self.stop_event = Event()
        signal.signal(signal.SIGTERM, self._exit)
        signal.signal(signal.SIGINT, self._exit)

    def _exit(self, *_):  # type: ignore
        self.stop_event.set()
        logging.getLogger(__name__).info("Shutdown requested – waiting for loop to exit")


class RealTimeSentimentProcessor:
    """
    Consumes from RAW_TOPIC, enriches messages with sentiment, publishes
    to ENRICHED_TOPIC. All infrastructure specifics (Kafka) are hidden
    behind minimal interfaces so that they can be swapped out easily.
    """

    def __init__(
        self,
        strategy: str = DEFAULT_STRATEGY,
        observers: Optional[Sequence[Observer]] = None,
        settings: Settings = SETTINGS,
    ) -> None:
        self._log = logging.getLogger(self.__class__.__name__)
        self._settings = settings

        # Strategy
        try:
            self._strategy: SentimentStrategy = STRATEGY_REGISTRY[strategy]()  # type: ignore
        except Exception as exc:
            self._log.error("Failed to init strategy '%s': %s – falling back to Dummy", strategy, exc)
            self._strategy = DummyStrategy()

        # Observers
        default_observers: List[Observer] = [LoggingObserver()]
        if MetricsObserver and Counter is not None:
            default_observers.append(MetricsObserver())
        self._observers: List[Observer] = list(observers or []) + default_observers

        # Validator
        self._validator = SchemaValidator()

        # Kafka I/O
        if KafkaConsumer is None or KafkaProducer is None:
            raise RuntimeError(
                "kafka-python not installed. Install with `pip install kafka-python`."
            )
        self._consumer = KafkaConsumer(
            self._settings.inbound_topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers.split(","),
            enable_auto_commit=False,
            group_id=self._settings.group_id,
            max_poll_records=self._settings.max_batch_size,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        )
        self._producer = KafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers.split(","),
            value_serializer=lambda d: json.dumps(d).encode("utf-8"),
        )

    # ------------------------- Processing Pipeline --------------------- #

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=0.5, min=1, max=10))
    def _safe_send(self, topic: str, value: Dict[str, Any]) -> None:
        """Send with retries on transient errors."""
        self._producer.send(topic, value=value).get(timeout=10)

    def _dispatch(self, event: SocialEvent, result: SentimentResult) -> None:
        for observer in self._observers:
            with suppress(Exception):
                observer.notify(event, result)

    def _enrich_payload(self, event: SocialEvent, result: SentimentResult) -> Dict[str, Any]:
        payload = event.to_dict()
        payload.update(
            {
                "sentiment_score": result.score,
                "sentiment_label": result.label,
                "processed_at": datetime.utcnow().isoformat(),
                "strategy": self._strategy.name,
            }
        )
        return payload

    # ----------------------------- Main loop --------------------------- #

    def run_forever(self) -> None:
        killer = GracefulKiller()
        self._log.info(
            "Starting RealTimeSentimentProcessor with strategy=%s, in_topic=%s, out_topic=%s",
            self._strategy.name,
            self._settings.inbound_topic,
            self._settings.outbound_topic,
        )

        while not killer.stop_event.is_set():
            batch = self._consumer.poll(timeout_ms=500)
            if not batch:
                continue

            for tp, records in batch.items():
                for record in records:
                    raw_payload = record.value
                    if not self._validator.validate(raw_payload):
                        self._log.warning("Schema validation failed, skipping event_id=%s", raw_payload.get("event_id"))
                        continue

                    try:
                        event = SocialEvent.from_dict(raw_payload)
                    except Exception as exc:
                        self._log.exception("Parsing error: %s – payload=%s", exc, raw_payload)
                        continue

                    start_time = time.perf_counter()
                    try:
                        result = self._strategy.analyze(event.text)
                    except Exception as exc:
                        self._log.exception("Strategy failure: %s – event_id=%s", exc, event.event_id)
                        continue
                    latency = time.perf_counter() - start_time

                    # Notify side-effect subscribers
                    self._dispatch(event, result)

                    # Publish enriched message
                    enriched = self._enrich_payload(event, result)
                    try:
                        self._safe_send(self._settings.outbound_topic, enriched)
                    except Exception as exc:  # retry handled inside _safe_send
                        self._log.exception("Kafka publish failed permanently: %s", exc)

                    # Manual offset commit (after successful processing)
                    self._consumer.commit()

                    # Metrics latency
                    if Counter is not None:
                        MetricsObserver()._latency.observe(latency)  # type: ignore

        self._shutdown()

    def _shutdown(self):
        self._log.info("Closing Kafka resources…")
        with suppress(Exception):
            self._consumer.close(10)
        with suppress(Exception):
            self._producer.flush(10)
            self._producer.close(10)
        self._log.info("Processor shut down cleanly")


# ---------------------------------- CLI ------------------------------------ #


def _parse_argv(argv: List[str]) -> Dict[str, Any]:
    import argparse

    parser = argparse.ArgumentParser(description="PulseStream Sentiment Processor")
    parser.add_argument(
        "-s",
        "--strategy",
        default=DEFAULT_STRATEGY,
        choices=list(STRATEGY_REGISTRY.keys()),
        help="Sentiment analysis back-end to use",
    )
    parser.add_argument("--log-level", default=SETTINGS.log_level, help="Python log level")
    return vars(parser.parse_args(argv))


def main(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    argv = argv or sys.argv[1:]
    cli_args = _parse_argv(argv)
    logging.getLogger().setLevel(cli_args["log_level"].upper())

    processor = RealTimeSentimentProcessor(strategy=cli_args["strategy"])
    processor.run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
```