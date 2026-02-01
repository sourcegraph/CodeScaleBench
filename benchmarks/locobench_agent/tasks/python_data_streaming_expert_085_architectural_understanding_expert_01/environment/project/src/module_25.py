```python
"""
module_25.py
============

A production-grade, self-contained slice of PulseStream Nexus’ streaming layer.
The module consumes raw social events from Kafka, validates & enriches them, and
publishes the upgraded record downstream.  It demonstrates:

1.  Clean-Architecture boundaries (entities, use-cases, infrastructure).
2.  Strategy pattern for pluggable enrichment.
3.  Great-Expectations-style validation via pydantic models.
4.  Observability: Prometheus metrics and structured logging.
5.  Fault-tolerance with exponential back-off and circuit-breaker semantics.

The code purposefully avoids proprietary dependencies so that it can be dropped
into any repo and executed with minimal external requirements
(`confluent-kafka`, `prometheus-client`, `pydantic`, and optionally
`transformers` if a real NLP model is desired).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Iterable, Optional

import prometheus_client
from pydantic import BaseModel, Field, ValidationError, validator

try:
    from confluent_kafka import Consumer, Producer, KafkaError, Message
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "confluent-kafka is required for streaming. "
        "Install with `pip install confluent-kafka`."
    ) from exc

# ------------------------------------------------------------------------------
# Configuration ----------------------------------------------------------------
# ------------------------------------------------------------------------------

DEFAULT_KAFKA_CONFIG: Dict[str, Any] = {
    "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
    "group.id": os.getenv("NEXUS_CONSUMER_GROUP", "pulse_nexus_ingestor"),
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
    "max.poll.interval.ms": 30_000,
    "session.timeout.ms": 10_000,
}

RAW_TOPIC = os.getenv("RAW_SOCIAL_TOPIC", "raw.social.events")
ENRICHED_TOPIC = os.getenv("ENRICHED_SOCIAL_TOPIC", "enriched.social.events")

# ------------------------------------------------------------------------------
# Logging & Observability ------------------------------------------------------
# ------------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)8s | %(name)s | %(message)s",
)
logger = logging.getLogger("pulsestream.module_25")

# Prometheus metrics
EVENTS_CONSUMED = prometheus_client.Counter(
    "pulsestream_events_consumed_total",
    "Total number of raw events consumed from Kafka.",
)
EVENTS_PUBLISHED = prometheus_client.Counter(
    "pulsestream_events_published_total",
    "Total number of enriched events produced to Kafka.",
)
EVENTS_VALIDATION_FAILED = prometheus_client.Counter(
    "pulsestream_events_validation_failed_total",
    "Number of raw events that failed schema validation.",
)
EVENTS_ENRICH_FAILED = prometheus_client.Counter(
    "pulsestream_events_enrich_failed_total",
    "Number of events that failed to be enriched (toxicity computation errors).",
)
EVENT_PROCESS_DURATION = prometheus_client.Histogram(
    "pulsestream_event_process_seconds",
    "Time spent processing a single event.",
)

# ------------------------------------------------------------------------------
# Domain Layer -----------------------------------------------------------------
# ------------------------------------------------------------------------------


class SocialEvent(BaseModel):
    """
    Canonical internal representation for a unit of social interaction.
    """

    event_id: str = Field(..., min_length=1)
    network: str  # e.g., twitter, reddit, mastodon
    actor_id: str
    content: str = Field(..., min_length=1, max_length=10_000)
    language: str = Field("und", min_length=2, max_length=8)
    timestamp: int = Field(
        ...,
        description="Epoch milliseconds when the social interaction occurred.",
        gt=1_000_000_000_000,  # After 2001
    )

    @validator("network")
    def network_must_be_supported(cls, v: str) -> str:  # noqa: N805
        supported = {"twitter", "reddit", "mastodon", "discord"}
        if v.lower() not in supported:
            raise ValueError(f"Unsupported network '{v}'. Supported={supported}")
        return v.lower()


class EnrichedSocialEvent(SocialEvent):
    """
    SocialEvent plus enrichment metadata.
    """

    toxicity: float = Field(..., ge=0.0, le=1.0)
    sentiment: Optional[float] = Field(
        None, description="Compound sentiment score in [-1, 1]."
    )

    class Config:  # noqa: D106
        orm_mode = True


# ------------------------------------------------------------------------------
# Enrichment Strategies --------------------------------------------------------
# ------------------------------------------------------------------------------


class ToxicityEnricher(ABC):
    """
    Strategy interface for toxicity enrichment.
    """

    name: str = "base"

    @abstractmethod
    def compute_toxicity(self, text: str) -> float:  # pragma: no cover
        """
        Return toxicity probability for the given text.
        0.0 means benign, 1.0 means extremely toxic.
        """
        raise NotImplementedError


class RuleBasedToxicityEnricher(ToxicityEnricher):
    """
    Very naive fallback strategy that looks for a curated list of swear words.
    Suitable for unit tests, not production.
    """

    name = "rule_based"
    _SWEAR_WORDS = {
        "damn",
        "shit",
        "fuck",
        "bitch",
        "bastard",
        "asshole",
        "dick",
    }

    def compute_toxicity(self, text: str) -> float:  # noqa: D401
        lowered = text.lower()
        hits = sum(word in lowered for word in self._SWEAR_WORDS)
        return min(1.0, hits / 3)  # heuristic cap


class TransformerToxicityEnricher(ToxicityEnricher):
    """
    Real-world strategy that loads a transformer model (e.g.,
    `unitary/toxic-bert`) to estimate toxicity.
    If the heavyweight dependency cannot be imported, we fall back to
    RuleBasedToxicityEnricher transparently.
    """

    name = "transformer"

    def __init__(self) -> None:
        try:
            from transformers import pipeline  # heavy import

            self._classifier = pipeline(
                "text-classification", model="unitary/toxic-bert", top_k=None
            )
            logger.info("Loaded transformer toxicity model 'unitary/toxic-bert'.")
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Could not load transformer model due to %s. "
                "Falling back to rule-based toxicity enrichment.",
                exc,
            )
            self._classifier = None

        if self._classifier is None:
            # Degrade gracefully
            self._fallback: ToxicityEnricher = RuleBasedToxicityEnricher()

    def compute_toxicity(self, text: str) -> float:  # noqa: D401
        if self._classifier is None:
            return self._fallback.compute_toxicity(text)

        try:
            scores = self._classifier(text)[0]
            # Convert list[dict] -> probability that label=="toxic"
            toxic_score = next(
                (s["score"] for s in scores if s["label"].lower() == "toxic"), 0.0
            )
            return float(toxic_score)
        except Exception as exc:  # pragma: no cover
            logger.exception("Transformer toxicity inference failed: %s", exc)
            return RuleBasedToxicityEnricher().compute_toxicity(text)


# ------------------------------------------------------------------------------
# Infrastructure / Kafka -------------------------------------------------------
# ------------------------------------------------------------------------------


@dataclass
class KafkaClients:
    """
    Convenience container to manage Kafka consumer & producer lifecycle.
    """

    consumer: Consumer
    producer: Producer


@contextmanager
def kafka_clients(
    consumer_conf: Dict[str, Any], producer_conf: Optional[Dict[str, Any]] = None
) -> Iterable[KafkaClients]:
    """
    Context manager that yields fully-configured Kafka consumer & producer.
    Handles graceful shutdown on SIGINT/SIGTERM.
    """

    producer_conf = producer_conf or {
        "bootstrap.servers": consumer_conf["bootstrap.servers"]
    }

    consumer = Consumer(consumer_conf)
    producer = Producer(producer_conf)

    interrupted = False

    def _signal_handler(signum, _frame) -> None:  # noqa: D401
        nonlocal interrupted
        logger.info("Received signal %s, terminating Kafka clients...", signum)
        interrupted = True
        consumer.close()
        producer.flush(5)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        yield KafkaClients(consumer=consumer, producer=producer)
    finally:
        if not interrupted:
            consumer.close()
            producer.flush(5)
        logger.info("Kafka clients closed.")


# ------------------------------------------------------------------------------
# Use-Case Interactor ----------------------------------------------------------
# ------------------------------------------------------------------------------


class ToxicityEnrichmentInteractor:
    """
    Clean-Architecture use-case that glues validation, enrichment, and I/O.
    """

    def __init__(
        self,
        *,
        toxicity_enricher: ToxicityEnricher,
        clients: KafkaClients,
        raw_topic: str = RAW_TOPIC,
        enriched_topic: str = ENRICHED_TOPIC,
        max_retries: int = 3,
        backoff_seconds: float = 1.5,
    ) -> None:
        self._enricher = toxicity_enricher
        self._consumer = clients.consumer
        self._producer = clients.producer
        self._raw_topic = raw_topic
        self._enriched_topic = enriched_topic
        self._max_retries = max_retries
        self._backoff = backoff_seconds

        self._consumer.subscribe([self._raw_topic])
        logger.info(
            "Enrichment interactor initialised. "
            "Raw topic=%s, enriched topic=%s, strategy=%s",
            self._raw_topic,
            self._enriched_topic,
            toxicity_enricher.name,
        )

    def _retryable(self, func: Callable[..., None]) -> Callable[..., None]:
        """
        Decorator to add retry with exponential back-off around message handler.
        """

        @wraps(func)
        def wrapper(msg: Message) -> None:
            attempt = 0
            while True:
                try:
                    func(msg)
                    break
                except Exception as exc:  # pragma: no cover
                    if attempt >= self._max_retries:
                        logger.error(
                            "Giving up after %d attempts: %s. Offending message: %s",
                            attempt,
                            exc,
                            msg.value(),
                        )
                        return
                    sleep_for = self._backoff * (2**attempt)
                    logger.warning(
                        "Error processing message (%s). Retrying in %.2fs...", exc, sleep_for
                    )
                    time.sleep(sleep_for)
                    attempt += 1

        return wrapper

    def _validate(self, payload: Dict[str, Any]) -> SocialEvent:
        """
        Validate payload against SocialEvent schema. Raises ValidationError.
        """
        return SocialEvent.parse_obj(payload)

    def _enrich(self, event: SocialEvent) -> EnrichedSocialEvent:
        """
        Compute toxicity & build EnrichedSocialEvent.
        """
        try:
            toxicity = self._enricher.compute_toxicity(event.content)
        except Exception as exc:  # pragma: no cover
            EVENTS_ENRICH_FAILED.inc()
            raise RuntimeError("Toxicity enrichment failed") from exc

        return EnrichedSocialEvent(**event.dict(), toxicity=toxicity)

    def _publish(self, enriched_event: EnrichedSocialEvent) -> None:
        """
        Serialize & publish enriched event to Kafka.
        """

        def _delivery_report(err: Optional[KafkaError], _msg: Message) -> None:
            if err is not None:  # pragma: no cover
                logger.error("Delivery failed: %s", err)

        self._producer.produce(
            self._enriched_topic,
            key=enriched_event.event_id.encode(),
            value=enriched_event.json().encode(),
            on_delivery=_delivery_report,
        )
        EVENTS_PUBLISHED.inc()

    def _handle_message(self, msg: Message) -> None:
        """
        Core message handler. Assumes retries handled by wrapper.
        """
        payload_bytes = msg.value()
        if payload_bytes is None:  # pragma: no cover
            logger.warning("Received Kafka tombstone message, skipping.")
            return

        try:
            payload = json.loads(payload_bytes)
        except json.JSONDecodeError as exc:  # pragma: no cover
            logger.error("Invalid JSON: %s", exc)
            EVENTS_VALIDATION_FAILED.inc()
            return

        try:
            event = self._validate(payload)
        except ValidationError as exc:
            logger.debug("Payload validation failed: %s", exc)
            EVENTS_VALIDATION_FAILED.inc()
            return

        start_time = time.perf_counter()
        enriched_event = self._enrich(event)
        self._publish(enriched_event)
        duration = time.perf_counter() - start_time
        EVENT_PROCESS_DURATION.observe(duration)
        EVENTS_CONSUMED.inc()

    def run_forever(self) -> None:
        """
        Blocking loop that consumes indefinitely until a termination signal
        closes the consumer.
        """
        logger.info("Interactor starting consume loop.")
        wrapped_handler = self._retryable(self._handle_message)

        while True:
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:  # pragma: no cover
                    continue  # Not an error
                logger.error("Kafka error: %s", msg.error())
                continue
            wrapped_handler(msg)
            self._consumer.commit(asynchronous=False)
            self._producer.poll(0)  # Trigger delivery callbacks


# ------------------------------------------------------------------------------
# Entrypoint -------------------------------------------------------------------
# ------------------------------------------------------------------------------


def main() -> None:  # noqa: D401
    """
    Example CLI entrypoint.  Typical usage:

        $ python -m src.module_25

    Metrics are exported on :8000 by default and can be scraped by Prometheus.
    """

    # Expose /metrics endpoint
    prometheus_port = int(os.getenv("PROMETHEUS_PORT", "8000"))
    prometheus_client.start_http_server(prometheus_port)
    logger.info("Prometheus metrics server started on :%s/metrics", prometheus_port)

    # Instantiate dependency graph
    toxicity_enricher: ToxicityEnricher
    strategy = os.getenv("TOXICITY_STRATEGY", "").lower()
    if strategy == "transformer":
        toxicity_enricher = TransformerToxicityEnricher()
    else:
        toxicity_enricher = RuleBasedToxicityEnricher()

    with kafka_clients(DEFAULT_KAFKA_CONFIG) as clients:
        interactor = ToxicityEnrichmentInteractor(
            toxicity_enricher=toxicity_enricher,
            clients=clients,
        )
        interactor.run_forever()


# ------------------------------------------------------------------------------
# Script Guard -----------------------------------------------------------------
# ------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting.")
        sys.exit(0)
```