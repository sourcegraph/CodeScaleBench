"""
PulseStream Nexus – module_41.py
================================

This module implements a *stream-side* enrichment micro-service that
subscribes to an inbound Kafka topic, validates each incoming social
event, transforms it via a configurable *Strategy* chain (sentiment
analysis, toxicity scoring, etc.), and republishes the enriched event
to an outbound topic.

Key concepts showcased
----------------------
• Clean-architecture separation inside a single file (Entities,
  Use-Cases, and Infrastructure abstractions).
• Strategy pattern for plug-n-play transformations.
• Transparent Prometheus metrics & structured logging.
• Resilient error handling and graceful degradation when optional
  dependencies are unavailable.

Notes
-----
• The code purposefully keeps 3rd-party dependencies optional; if they
  cannot be imported at runtime, the system falls back to safe-no-ops so
  that the micro-service can still start (useful for local testing).
• In production, install:
    kafka-python>=2.0.2
    prometheus-client>=0.16.0
    textblob>=0.18.0           # illustrative sentiment scorer
    better-profanity>=0.7.0    # illustrative toxicity scorer
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --------------------------------------------------------------------------- #
# Optional third-party libraries
# --------------------------------------------------------------------------- #
with suppress(ImportError):
    from kafka import KafkaConsumer, KafkaProducer  # type: ignore
with suppress(ImportError):
    from prometheus_client import Counter, Gauge, Histogram, start_http_server  # type: ignore
with suppress(ImportError):
    from textblob import TextBlob  # type: ignore
with suppress(ImportError):
    from better_profanity import profanity  # type: ignore


# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format=(
        "%(asctime)s %(levelname)-8s [%(threadName)s] "
        "%(name)s – %(message)s"
    ),
)
logger = logging.getLogger("pulse.module_41")


# --------------------------------------------------------------------------- #
# Domain layer – entities & value objects
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SocialEvent:
    """
    Canonical representation of a social event as it flows through the
    PulseStream pipeline.
    """

    event_id: str
    user_id: str
    text: str
    network: str
    created_at: datetime
    extra: Dict[str, Any] = field(default_factory=dict)

    # Enrichment fields
    sentiment: Optional[float] = None
    toxicity: Optional[float] = None

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "SocialEvent":
        try:
            created = datetime.fromisoformat(raw["created_at"])
        except (KeyError, ValueError) as exc:
            raise ValidationError("Invalid 'created_at' field") from exc

        return SocialEvent(
            event_id=str(raw["event_id"]),
            user_id=str(raw["user_id"]),
            text=str(raw["text"]),
            network=str(raw["network"]),
            created_at=created,
            extra=raw.get("extra", {}),
        )

    def to_json(self) -> bytes:
        # datetime serialization
        payload = {
            **self.__dict__,
            "created_at": self.created_at.isoformat(),
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------- #
# Error definitions
# --------------------------------------------------------------------------- #
class ValidationError(Exception):
    """Raised when an input event fails schema/basic guardrails."""


class TransformationError(Exception):
    """Raised when a TransformationStrategy fails unexpectedly."""


# --------------------------------------------------------------------------- #
# Transformation strategies (Strategy Pattern)
# --------------------------------------------------------------------------- #
class TransformationStrategy(ABC):
    """Abstract base class for event transformation strategies."""

    @abstractmethod
    def transform(self, event: SocialEvent) -> SocialEvent:
        """Return the modified event or raise TransformationError."""


class SentimentTransformation(TransformationStrategy):
    """Sentiment scoring using TextBlob or simple fallback."""

    def __init__(self) -> None:
        if "TextBlob" not in globals():
            logger.warning("TextBlob not available – sentiment disabled")
        self._enabled = "TextBlob" in globals()

    def transform(self, event: SocialEvent) -> SocialEvent:
        if not self._enabled:
            return event  # No-op

        try:
            blob = TextBlob(event.text)
            # Polarity range −1..1. Normalise to 0..1 for convenience
            event.sentiment = (blob.sentiment.polarity + 1) / 2
            return event
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Sentiment transformation failed: %s", exc)
            raise TransformationError from exc


class ToxicityTransformation(TransformationStrategy):
    """Toxicity estimation via ‘better-profanity’ word list."""

    def __init__(self) -> None:
        if "profanity" not in globals():
            logger.warning("better_profanity not available – toxicity disabled")
        else:
            profanity.load_censor_words()
        self._enabled = "profanity" in globals()

    def transform(self, event: SocialEvent) -> SocialEvent:
        if not self._enabled:
            return event  # No-op

        try:
            # Very naive metric: proportion of profane words.
            tokens = [tok.lower() for tok in event.text.split()]
            if not tokens:
                event.toxicity = 0.0
                return event

            profane_count = sum(1 for tok in tokens if profanity.contains_profanity(tok))
            event.toxicity = profane_count / len(tokens)
            return event
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Toxicity transformation failed: %s", exc)
            raise TransformationError from exc


# --------------------------------------------------------------------------- #
# Use-case layer – event processor
# --------------------------------------------------------------------------- #
class EventProcessor:
    """
    Orchestrates event validation and transformation before delegating the
    enriched event downstream (e.g., republishing to Kafka).
    """

    def __init__(self, strategies: Sequence[TransformationStrategy]) -> None:
        self.strategies: List[TransformationStrategy] = list(strategies)

    def process(self, raw: Dict[str, Any]) -> SocialEvent:
        # 1) Validate / canonicalise
        try:
            event = SocialEvent.from_dict(raw)
        except ValidationError:
            # bubble up – infrastructure decides what to do
            raise

        # 2) Transform via chain of strategies
        for strategy in self.strategies:
            event = strategy.transform(event)

        return event


# --------------------------------------------------------------------------- #
# Infrastructure layer – Kafka adaptor & monitoring
# --------------------------------------------------------------------------- #
class KafkaTransformerService(threading.Thread):
    """
    Background thread that reads from an input Kafka topic, processes each
    event, and writes to an output topic. Metrics are exported to Prometheus.
    """

    daemon = True  # allow program exit even if thread is running

    # Metrics (initialised lazily to avoid ImportError issues)
    _metrics_created = False

    def __init__(
        self,
        bootstrap_servers: str,
        in_topic: str,
        out_topic: str,
        group_id: str,
        processor: EventProcessor,
        poll_timeout: float = 1.0,
        prometheus_port: int = 8000,
    ) -> None:
        super().__init__(name="KafkaTransformerService")
        self.bootstrap_servers = bootstrap_servers
        self.in_topic = in_topic
        self.out_topic = out_topic
        self.group_id = group_id
        self.poll_timeout = poll_timeout
        self.processor = processor
        self._shutdown = threading.Event()

        if "KafkaConsumer" not in globals() or "KafkaProducer" not in globals():
            raise RuntimeError(
                "kafka-python must be installed to run KafkaTransformerService"
            )

        self.consumer = KafkaConsumer(
            self.in_topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
        )

        self.producer = KafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: v,  # already bytes after to_json
        )

        self._setup_metrics(prometheus_port)

    # --------------------------------------------------------------------- #
    # Metrics helpers
    # --------------------------------------------------------------------- #
    def _setup_metrics(self, port: int) -> None:
        if "Counter" not in globals():
            logger.warning("prometheus_client not available – metrics disabled")
            return

        if not KafkaTransformerService._metrics_created:
            # Expose /metrics HTTP endpoint only once
            start_http_server(port)  # type: ignore
            KafkaTransformerService._metrics_created = True
            logger.info("Prometheus metrics exporter started on :%d", port)

        # Metric instances
        self.msg_in_total: Counter = Counter(  # type: ignore
            "psn_ingest_messages_total",
            "Total number of inbound messages",
            ["topic", "network"],
        )
        self.msg_out_total: Counter = Counter(  # type: ignore
            "psn_enriched_messages_total",
            "Total number of outbound enriched messages",
            ["topic", "network"],
        )
        self.msg_errors_total: Counter = Counter(  # type: ignore
            "psn_processing_errors_total",
            "Total number of messages failed during processing",
            ["topic", "error_type"],
        )
        self.msg_latency: Histogram = Histogram(  # type: ignore
            "psn_processing_latency_seconds",
            "Time from event creation to enrichment",
            buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
        )
        self.service_up: Gauge = Gauge(  # type: ignore
            "psn_transformer_service_up",
            "Health metric (1=up, 0=down)",
        )
        self.service_up.set(1)

    # --------------------------------------------------------------------- #
    # Thread main loop
    # --------------------------------------------------------------------- #
    def run(self) -> None:
        logger.info(
            "KafkaTransformerService consuming from '%s' producing to '%s'",
            self.in_topic,
            self.out_topic,
        )

        while not self._shutdown.is_set():
            batch = self.consumer.poll(timeout_ms=int(self.poll_timeout * 1000))
            for _tp, messages in batch.items():
                for msg in messages:
                    self._handle_message(msg)

        # Flush & close I/O
        logger.info("Shutting down KafkaTransformerService …")
        with suppress(Exception):
            self.consumer.close()
        with suppress(Exception):
            self.producer.flush()
            self.producer.close()

        # health gauge
        if "Gauge" in globals():
            self.service_up.set(0)

    def _handle_message(self, msg: Any) -> None:
        raw_event = msg.value
        network = raw_event.get("network", "unknown")

        # Metrics
        if "Counter" in globals():
            self.msg_in_total.labels(topic=self.in_topic, network=network).inc()

        try:
            enriched = self.processor.process(raw_event)

            # Latency metric (wall-clock creation vs enrichment time)
            if "Histogram" in globals():
                delta = (datetime.now(timezone.utc) - enriched.created_at).total_seconds()
                self.msg_latency.observe(delta)

            # Send downstream
            self.producer.send(self.out_topic, enriched.to_json())
            self.consumer.commit()

            if "Counter" in globals():
                self.msg_out_total.labels(topic=self.out_topic, network=network).inc()

        except (ValidationError, TransformationError) as exc:
            logger.warning("Dropping message due to processing error: %s", exc)

            if "Counter" in globals():
                self.msg_errors_total.labels(
                    topic=self.in_topic, error_type=exc.__class__.__name__
                ).inc()

        except Exception as exc:  # pylint: disable=broad-except
            # Unhandled – propagate to raise alert & stop
            logger.exception("Unexpected error: %s", exc)
            self._shutdown.set()

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def shutdown(self, *_sig: object) -> None:
        logger.info("Received shutdown signal, stopping consumer loop")
        self._shutdown.set()


# --------------------------------------------------------------------------- #
# CLI entrypoint
# --------------------------------------------------------------------------- #
def _build_processor() -> EventProcessor:
    """
    Build the EventProcessor with whichever strategies are viable in the
    current runtime environment.
    """
    strategies: List[TransformationStrategy] = [
        SentimentTransformation(),
        ToxicityTransformation(),
    ]
    return EventProcessor(strategies=strategies)


def main() -> None:
    """
    Example CLI runner. Environment variables control connection details so
    that the script can be configured via Kubernetes/Compose secrets:

        KAFKA_BOOTSTRAP_SERVERS=broker:9092
        KAFKA_IN_TOPIC=social_raw
        KAFKA_OUT_TOPIC=social_enriched
        KAFKA_GROUP_ID=psn-transformer-v1
        PROMETHEUS_PORT=8000
    """
    cfg = {
        "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        "in_topic": os.getenv("KAFKA_IN_TOPIC", "social_raw"),
        "out_topic": os.getenv("KAFKA_OUT_TOPIC", "social_enriched"),
        "group_id": os.getenv("KAFKA_GROUP_ID", "psn-transformer"),
        "prometheus_port": int(os.getenv("PROMETHEUS_PORT", "8000")),
    }

    processor = _build_processor()
    service = KafkaTransformerService(
        bootstrap_servers=cfg["bootstrap_servers"],
        in_topic=cfg["in_topic"],
        out_topic=cfg["out_topic"],
        group_id=cfg["group_id"],
        processor=processor,
        prometheus_port=cfg["prometheus_port"],
    )

    # Ensure graceful shutdown on SIGINT/SIGTERM
    signal.signal(signal.SIGINT, service.shutdown)
    signal.signal(signal.SIGTERM, service.shutdown)

    service.start()

    # Block main thread until service terminates
    try:
        while service.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt – shutting down")
        service.shutdown()

    service.join()
    logger.info("Service stopped")


# --------------------------------------------------------------------------- #
# Run when executed as script
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    try:
        main()
    except RuntimeError as err:
        logger.error("Failed to start service: %s", err)
        sys.exit(1)
