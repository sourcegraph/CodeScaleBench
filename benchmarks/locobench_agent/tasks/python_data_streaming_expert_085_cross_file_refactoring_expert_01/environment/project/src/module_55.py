```python
"""
PulseStream Nexus – Ingestion Worker
File: src/module_55.py

This module houses a self-contained ingestion worker responsible for
pulling raw events from a Kafka topic (e.g., `raw_social_events`),
performing schema validation and enrichment, and finally dispatching the
cleaned events to a downstream topic (`enriched_social_events`) for
further processing by other micro-services.

Clean-architecture wise this file mixes a thin slice of “interface
adapter” (Kafka wiring) with “application” (use-case orchestration).
Domain logic is intentionally kept minimal and pluggable via
`BaseTransformer` strategies.

The implementation purposely avoids hard project-level dependencies and
gracefully degrades when optional libraries (e.g., TextBlob, Detoxify,
Prometheus, Sentry) are missing.

Copyright 2024
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# 3rd-party (optional) deps ----------------------------------------------------
# Kafka client
try:
    from confluent_kafka import Consumer, Producer, KafkaException  # type: ignore
except ImportError:  # pragma: no cover
    Consumer = Producer = KafkaException = None  # type: ignore

# Data validation
try:
    from pydantic import BaseModel, ValidationError  # type: ignore
except ImportError:  # pragma: no cover

    class BaseModel:  # minimal shim
        def __init__(self, **kw):  # noqa: D401
            for k, v in kw.items():
                setattr(self, k, v)

        def dict(self):  # type: ignore
            return self.__dict__

    class ValidationError(Exception):  # noqa: D401
        pass


# Sentiment analysis
try:
    from textblob import TextBlob  # type: ignore
except ImportError:  # pragma: no cover

    class TextBlob:  # fallback stub
        def __init__(self, text: str):
            self.text = text

        @property
        def sentiment(self):
            # neutral sentiment: polarity=0, subjectivity=0
            return type(
                "Sentiment",
                (),
                {"polarity": 0.0, "subjectivity": 0.0},
            )()


# Toxicity detection
try:
    from detoxify import Detoxify  # type: ignore
except ImportError:  # pragma: no cover
    Detoxify = None  # type: ignore

# Observability
try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server  # type: ignore
except ImportError:  # pragma: no cover

    class _NoopMetric:  # noqa: D401
        def __getattr__(self, name):  # type: ignore
            return lambda *args, **kwargs: None

        def __call__(self, *args, **kwargs):  # type: ignore
            return self

    Counter = Gauge = Histogram = lambda *_, **__: _NoopMetric()  # type: ignore

# Error monitoring
try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover

    class _NoopSentry:  # noqa: D401
        @staticmethod
        def init(*_, **__):
            pass

        @staticmethod
        def capture_exception(*_, **__):
            pass

    sentry_sdk = _NoopSentry()  # type: ignore

# -----------------------------------------------------------------------------
__all__ = [
    "IngestionWorker",
    "BaseTransformer",
    "SentimentTransformer",
    "ToxicityTransformer",
    "EventSchema",
]

_KAFKA_ENABLED = Consumer is not None
_LOGGER = logging.getLogger("pulsestream.ingestion")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# Prometheus metrics ----------------------------------------------------------
METRICS_PORT = int(os.getenv("METRICS_PORT", "9404"))
_INGESTED_MSG_COUNTER = Counter("ingested_messages_total", "Total ingested messages")
_VALIDATION_FAIL_COUNTER = Counter(
    "validation_fail_total", "Events failing schema validation"
)
_TRANSFORM_FAIL_COUNTER = Counter(
    "transform_fail_total", "Events failing during transformation"
)
_PROCESSED_MSG_COUNTER = Counter(
    "processed_messages_total", "Events successfully processed"
)
_PROCESSING_LATENCY = Histogram(
    "processing_latency_seconds", "End-to-end processing latency"
)


# -----------------------------------------------------------------------------
# Domain schema
# -----------------------------------------------------------------------------


class EventSchema(BaseModel):
    """
    Pydantic event schema used for validation.

    Expected shape:
        {
            "id": str,
            "timestamp": int (epoch millis),
            "source": str,           # e.g., 'twitter'
            "user_id": str,
            "text": str,
            "meta": dict
        }
    """

    id: str
    timestamp: int
    source: str
    user_id: str
    text: str
    meta: Dict[str, Any]


# -----------------------------------------------------------------------------
# Transformer strategies
# -----------------------------------------------------------------------------
class BaseTransformer(ABC):
    """
    Abstract base class for enrichment strategies.
    """

    @abstractmethod
    def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply transformation and return the enriched payload.
        """


class SentimentTransformer(BaseTransformer):
    """
    Adds simple sentiment scoring using TextBlob.

    Output fields:
        sentiment: {
            polarity: float (-1 to 1),
            subjectivity: float (0 to 1)
        }
    """

    def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        blob = TextBlob(data.get("text", ""))
        sentiment = {"polarity": blob.sentiment.polarity, "subjectivity": blob.sentiment.subjectivity}
        data["sentiment"] = sentiment
        return data


class ToxicityTransformer(BaseTransformer):
    """
    Adds toxicity probability using Detoxify’s neutral model.
    """

    _model = None

    def __init__(self) -> None:
        if Detoxify is not None and ToxicityTransformer._model is None:
            # model load can be expensive
            ToxicityTransformer._model = Detoxify("original", device="cpu")
        elif Detoxify is None:
            _LOGGER.warning("Detoxify not available; ToxicityTransformer will be a noop.")

    def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if Detoxify is None or ToxicityTransformer._model is None:
            data["toxicity"] = {"toxicity": 0.0}
            return data

        scores = ToxicityTransformer._model.predict(data.get("text", ""))
        data["toxicity"] = scores
        return data


# -----------------------------------------------------------------------------
# Kafka helper utilities
# -----------------------------------------------------------------------------
@dataclass
class KafkaConfig:
    bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    group_id: str = os.getenv("KAFKA_CONSUMER_GROUP", "pulsestream_ingestion")
    auto_offset_reset: str = "latest"
    enable_auto_commit: bool = False
    security_protocol: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    sasl_mechanism: Optional[str] = os.getenv("KAFKA_SASL_MECHANISM") or None
    sasl_username: Optional[str] = os.getenv("KAFKA_SASL_USERNAME") or None
    sasl_password: Optional[str] = os.getenv("KAFKA_SASL_PASSWORD") or None
    ssl_cafile: Optional[str] = os.getenv("KAFKA_SSL_CA") or None

    def consumer_conf(self) -> Dict[str, Any]:
        conf = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
            "security.protocol": self.security_protocol,
        }
        # optional security fields
        optional_fields = [
            ("sasl.mechanisms", self.sasl_mechanism),
            ("sasl.username", self.sasl_username),
            ("sasl.password", self.sasl_password),
            ("ssl.ca.location", self.ssl_cafile),
        ]
        conf.update({k: v for k, v in optional_fields if v})
        return conf

    def producer_conf(self) -> Dict[str, Any]:
        # Ingest and egress security config are identical for simplicity.
        return self.consumer_conf()


# -----------------------------------------------------------------------------
# Ingestion Worker
# -----------------------------------------------------------------------------


class IngestionWorker:
    """
    Consumes raw social events, validates & enriches, and republishes.

    Usage:
        worker = IngestionWorker()
        worker.run()  # blocking

    A graceful shutdown is managed by catching SIGINT / SIGTERM signals.
    """

    RAW_TOPIC = os.getenv("RAW_TOPIC", "raw_social_events")
    OUT_TOPIC = os.getenv("ENRICHED_TOPIC", "enriched_social_events")
    BATCH_SIZE = 256
    POLL_TIMEOUT_SECS = 1.0

    def __init__(
        self,
        kafka_cfg: Optional[KafkaConfig] = None,
        transformers: Optional[List[BaseTransformer]] = None,
    ):
        self.kafka_cfg = kafka_cfg or KafkaConfig()
        self.transformers = transformers or [
            SentimentTransformer(),
            ToxicityTransformer(),
        ]

        if not _KAFKA_ENABLED:
            raise RuntimeError("confluent_kafka package is required but not installed.")

        self._consumer = Consumer(self.kafka_cfg.consumer_conf())
        self._producer = Producer(self.kafka_cfg.producer_conf())
        self._running = False

    # ---------------------------------------------------------------------
    # High-level orchestration
    # ---------------------------------------------------------------------
    def run(self) -> None:
        """
        Entrypoint – blocks indefinitely until a stop signal is received.
        """
        self._setup_signal_handlers()
        _LOGGER.info("Starting ingestion worker (%s → %s)...", self.RAW_TOPIC, self.OUT_TOPIC)
        self._consumer.subscribe([self.RAW_TOPIC])

        if METRICS_PORT:
            start_http_server(METRICS_PORT)
            _LOGGER.info("Prometheus metrics exposed on :%s", METRICS_PORT)

        self._running = True
        try:
            while self._running:
                self._poll_and_process()
        finally:
            self._shutdown()

    # ---------------------------------------------------------------------
    # Core loop
    # ---------------------------------------------------------------------
    def _poll_and_process(self) -> None:
        """
        Poll Kafka, process events in small batches to amortize overhead.
        """
        messages = self._consumer.consume(num_messages=self.BATCH_SIZE, timeout=self.POLL_TIMEOUT_SECS)
        if not messages:
            return

        for msg in messages:
            if msg is None or msg.error():
                _LOGGER.error("Kafka message error: %s", msg.error())
                continue

            _INGESTED_MSG_COUNTER.inc()

            try:
                decoded = json.loads(msg.value().decode("utf-8"))
            except json.JSONDecodeError as exc:
                _VALIDATION_FAIL_COUNTER.inc()
                _LOGGER.warning("Invalid JSON payload: %s", exc)
                continue

            start_time = time.time()
            try:
                # Validation
                event = EventSchema(**decoded)
                data = event.dict()

                # Enrichment
                for transformer in self.transformers:
                    data = transformer.transform(data)

                # Dispatch
                self._dispatch(data)
                _PROCESSED_MSG_COUNTER.inc()
                _PROCESSING_LATENCY.observe(time.time() - start_time)

            except ValidationError as exc:
                _VALIDATION_FAIL_COUNTER.inc()
                _LOGGER.warning("Schema validation failed for id=%s: %s", decoded.get("id"), exc)
                sentry_sdk.capture_exception(exc)

            except Exception as exc:  # noqa: BLE001
                _TRANSFORM_FAIL_COUNTER.inc()
                _LOGGER.exception("Unexpected processing error for id=%s", decoded.get("id"))
                sentry_sdk.capture_exception(exc)

    # ---------------------------------------------------------------------
    # Kafka publishing
    # ---------------------------------------------------------------------
    def _dispatch(self, data: Dict[str, Any]) -> None:  # noqa: D401
        payload = json.dumps(data).encode("utf-8")

        def _delivery_report(err: Optional[KafkaException], _: Any) -> None:
            if err is not None:
                _LOGGER.error("Delivery failed: %s", err)
                sentry_sdk.capture_exception(err)

        self._producer.produce(self.OUT_TOPIC, payload, callback=_delivery_report)
        # Confluent-Kafka recommends flushing regularly (not per message)
        self._producer.poll(0)

    # ---------------------------------------------------------------------
    # Signal & shutdown handling
    # ---------------------------------------------------------------------
    def stop(self) -> None:
        """
        External method to initiate a graceful shutdown.
        """
        _LOGGER.info("Shutdown requested by user.")
        self._running = False

    def _setup_signal_handlers(self) -> None:
        loop = asyncio.get_event_loop()

        def _handler(signo: int, _frame: Any) -> None:
            _LOGGER.info("Caught signal %s – initiating shutdown.", signal.Signals(signo).name)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handler, sig, None)  # type: ignore[arg-type]
            except NotImplementedError:  # Windows
                signal.signal(sig, _handler)  # type: ignore[arg-type]

    def _shutdown(self) -> None:
        """
        Flush producers and close consumer cleanly.
        """
        _LOGGER.info("Flushing producer queue...")
        self._producer.flush()
        _LOGGER.info("Committing offsets and closing consumer...")
        self._consumer.commit(asynchronous=False)
        self._consumer.close()
        _LOGGER.info("Shutdown complete.")


# -----------------------------------------------------------------------------
# Top-level CLI
# -----------------------------------------------------------------------------
def _configure_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENVIRONMENT", "development"),
            release=os.getenv("RELEASE", "dev"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES", "0.0")),
        )
        _LOGGER.info("Sentry initialized.")
    else:
        _LOGGER.info("Sentry disabled (no DSN provided).")


def main() -> None:  # pragma: no cover
    """
    Minimal CLI for running the worker standalone.

    Usage:
        python -m src.module_55
    """
    _configure_sentry()
    try:
        worker = IngestionWorker()
    except RuntimeError as exc:
        _LOGGER.critical(exc)
        sys.exit(1)

    worker.run()


if __name__ == "__main__":  # pragma: no cover
    main()
```