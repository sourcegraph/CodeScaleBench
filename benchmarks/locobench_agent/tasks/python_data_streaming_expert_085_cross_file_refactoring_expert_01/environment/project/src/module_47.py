```python
"""
src/module_47.py
================

Real-time enrichment processor for PulseStream Nexus.

This module consumes *raw* social-network events from Kafka, validates and
enriches them (toxicity + sentiment), and publishes the enriched payload to a
downstream topic.  It follows Clean-Architecture principles:  business rules are
kept in pure “strategy” objects (e.g., classifiers) that are independent from
I/O concerns.  Observability is provided through Prometheus metrics and
Sentry.io tracing.

The file is intentionally self-contained so that it can be deployed as a
stand-alone micro-service (Docker/Poetry/etc.).  Configuration is driven by
environment variables in order to simplify container orchestration.

Author: PulseStream Nexus team
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from pydantic import BaseModel, ValidationError
from prometheus_client import Counter, Histogram, start_http_server

# Optional — do *not* hard-depend.  If libraries are missing the app will still
# start but advanced functionality (e.g., Perspective API) will be disabled.
try:
    # google-api-python-client (Perspective API) is heavy; lazy import.
    from googleapiclient.discovery import build  # type: ignore
except ImportError:  # pragma: no cover
    build = None  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore


###############################################################################
# Logging setup                                                               #
###############################################################################

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    stream=sys.stdout,
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("pulse_stream.module_47")


###############################################################################
# Prometheus instrumentation                                                  #
###############################################################################

REQUEST_COUNT = Counter(
    "psn_enricher_messages_total",
    "Number of messages processed by the enricher.",
    ["status", "topic"],
)
REQUEST_LATENCY = Histogram(
    "psn_enricher_latency_seconds",
    "End-to-end latency per message.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 5, 15),
)

PROM_PORT = int(os.getenv("PROM_PORT", 9000))
start_http_server(PROM_PORT)
logger.info("Prometheus metrics exposed on :%s", PROM_PORT)

###############################################################################
# Sentry – optional, only when DSN is provided                                #
###############################################################################

if sentry_sdk and (dsn := os.getenv("SENTRY_DSN")):
    sentry_sdk.init(dsn=dsn, traces_sample_rate=float(os.getenv("SENTRY_SAMPLE", 0.1)))
    logger.info("Sentry initialized")
else:
    logger.info("Sentry disabled (missing SDK or DSN)")


###############################################################################
# Domain models                                                               #
###############################################################################

class RawSocialEvent(BaseModel):
    """Schema for incoming social-network events."""

    id: str
    platform: str  # e.g., twitter, reddit, mastodon
    user_id: str
    text: str
    timestamp: float
    metadata: Optional[Dict[str, Any]] = None


class EnrichedSocialEvent(RawSocialEvent):
    """Outgoing, enriched event."""

    toxicity: float
    sentiment: float
    is_viral: bool


###############################################################################
# Strategy Pattern for classification                                         #
###############################################################################

@runtime_checkable
class ToxicityClassifier(Protocol):
    """Return a toxicity score between 0.0 (safe) and 1.0 (toxic)."""

    def score(self, text: str) -> float: ...


@runtime_checkable
class SentimentAnalyzer(Protocol):
    """Return sentiment polarity between −1.0 (negative) and +1.0 (positive)."""

    def polarity(self, text: str) -> float: ...


class DummyToxicityClassifier:
    """Faster, deterministic classifier for testing/demo."""

    def score(self, text: str) -> float:
        # Very naïve: long messages are “more toxic”.
        return min(len(text) / 280.0, 1.0)


class PerspectiveAPIToxicityClassifier:
    """Google Perspective API implementation.

    Requires PERSPECTIVE_API_KEY env-variable and google-api-python-client.
    """

    _client: Any
    _attr: str = "TOXICITY"

    def __init__(self, api_key: str) -> None:
        if not build:
            raise RuntimeError("google-api-python-client not installed")
        self._client = build(
            "commentanalyzer", "v1alpha1", developerKey=api_key, cache_discovery=False
        )

    def score(self, text: str) -> float:
        body = {
            "comment": {"text": text},
            "requestedAttributes": {self._attr: {}},
        }
        result = (
            self._client.comments()
            .analyze(body=body)
            .execute(num_retries=1)  # type: ignore[no-any-return]
        )
        return (
            result["attributeScores"][self._attr]["summaryScore"]["value"]  # type: ignore[index]
        )


class NaiveSentimentAnalyzer:
    """LoFi sentiment using word lists; replace with ML model in prod."""

    _POS = {"good", "great", "awesome", "love", "cool", "nice"}
    _NEG = {"bad", "terrible", "hate", "awful", "sucks", "angry"}

    def polarity(self, text: str) -> float:
        words = set(text.lower().split())
        pos_hits = len(words & self._POS)
        neg_hits = len(words & self._NEG)
        total = pos_hits + neg_hits or 1
        return (pos_hits - neg_hits) / total


###############################################################################
# Kafka helpers                                                               #
###############################################################################

def _create_consumer(topic: str) -> KafkaConsumer:
    """Create and configure the Kafka consumer."""
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    group_id = os.getenv("KAFKA_CONSUMER_GROUP", "psn_enricher_group")

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=servers.split(","),
        group_id=group_id,
        enable_auto_commit=False,
        value_deserializer=lambda m: m.decode("utf-8"),
        consumer_timeout_ms=1000,  # Allow graceful shutdown
    )
    logger.info("KafkaConsumer connected to %s (topic=%s)", servers, topic)
    return consumer


def _create_producer() -> KafkaProducer:
    """Create and configure the Kafka producer."""
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    producer = KafkaProducer(
        bootstrap_servers=servers.split(","),
        value_serializer=lambda m: json.dumps(m).encode("utf-8"),
        retries=5,
        linger_ms=10,
    )
    logger.info("KafkaProducer connected to %s", servers)
    return producer


###############################################################################
# Graceful shutdown                                                           #
###############################################################################

class ShutdownSignal(Exception):
    """Raised internally to stop the consuming loop."""


@contextmanager
def graceful_shutdown() -> Any:
    """Context manager catching SIGTERM/SIGINT and raising ShutdownSignal."""

    def _raise(*_: Any) -> None:  # noqa: D401,S110
        raise ShutdownSignal()

    original_int = signal.getsignal(signal.SIGINT)
    original_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _raise)
    signal.signal(signal.SIGTERM, _raise)

    try:
        yield
    finally:
        signal.signal(signal.SIGINT, original_int)
        signal.signal(signal.SIGTERM, original_term)


###############################################################################
# Enricher core                                                               #
###############################################################################

class StreamEnricher:
    """High-level coordinator that ties everything together."""

    def __init__(
        self,
        in_topic: str,
        out_topic: str,
        toxicity_classifier: ToxicityClassifier,
        sentiment_analyzer: SentimentAnalyzer,
    ) -> None:
        self._in_topic = in_topic
        self._out_topic = out_topic
        self._toxicity = toxicity_classifier
        self._sentiment = sentiment_analyzer
        self._consumer = _create_consumer(in_topic)
        self._producer = _create_producer()

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        """Run forever (until SIGTERM)."""

        logger.info("Enricher started (→ %s)", self._out_topic)
        with graceful_shutdown():
            while True:
                try:
                    self._process_batch()
                except ShutdownSignal:
                    logger.info("Shutdown requested — terminating …")
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Uncaught exception: %s", exc)
                    if sentry_sdk:
                        sentry_sdk.capture_exception(exc)

        self._clean_exit()

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #

    def _process_batch(self) -> None:
        """Poll Kafka, process messages, and commit offsets."""
        records = self._consumer.poll(timeout_ms=500)
        for tp, msgs in records.items():
            for message in msgs:
                self._process_single(message.value)
        if records:
            # Commit *after* successful processing to avoid message loss.
            self._consumer.commit()

    @REQUEST_LATENCY.time()  # Prometheus decorator
    def _process_single(self, raw_value: str) -> None:
        """Validate + enrich single message.  Raises no exceptions."""
        try:
            event = RawSocialEvent.parse_raw(raw_value)
        except ValidationError as err:
            logger.warning("Invalid message skipped: %s", err)
            REQUEST_COUNT.labels(status="validation_error", topic=self._in_topic).inc()
            return

        try:
            enriched = self._enrich(event)
            self._producer.send(self._out_topic, enriched.dict())
            REQUEST_COUNT.labels(status="ok", topic=self._in_topic).inc()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Processing failed: %s", exc)
            REQUEST_COUNT.labels(status="processing_error", topic=self._in_topic).inc()
            if sentry_sdk:
                sentry_sdk.capture_exception(exc)

    def _enrich(self, event: RawSocialEvent) -> EnrichedSocialEvent:
        """Business rules — Pure function, deterministic."""
        toxicity_score = self._toxicity.score(event.text)
        sentiment_score = self._sentiment.polarity(event.text)
        is_viral = random.random() < 0.05  # TODO: implement a real model

        return EnrichedSocialEvent(
            **event.dict(),
            toxicity=toxicity_score,
            sentiment=sentiment_score,
            is_viral=is_viral,
        )

    def _clean_exit(self) -> None:
        """Flush producer and close network connections."""
        logger.info("Flushing producer …")
        try:
            self._producer.flush(timeout=5)
        except KafkaError as exc:
            logger.warning("Flush failed: %s", exc)
        finally:
            self._producer.close()
            self._consumer.close()
        logger.info("Shutdown complete")


###############################################################################
# Factory & entry-point                                                      #
###############################################################################

def _build_classifier() -> ToxicityClassifier:
    """Select toxicity classifier based on environment."""
    api_key = os.getenv("PERSPECTIVE_API_KEY")
    if api_key:
        try:
            logger.info("Using PerspectiveAPI classifier")
            return PerspectiveAPIToxicityClassifier(api_key=api_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PerspectiveAPI unavailable (%s); falling back → dummy", exc)
    logger.info("Using DummyToxicityClassifier")
    return DummyToxicityClassifier()


def main() -> None:  # noqa: D401
    """CLI entry-point: `python -m src.module_47`."""
    in_topic = os.getenv("IN_TOPIC", "raw_social_events")
    out_topic = os.getenv("OUT_TOPIC", "enriched_social_events")

    enricher = StreamEnricher(
        in_topic=in_topic,
        out_topic=out_topic,
        toxicity_classifier=_build_classifier(),
        sentiment_analyzer=NaiveSentimentAnalyzer(),
    )
    enricher.start()


if __name__ == "__main__":  # pragma: no cover
    main()
```