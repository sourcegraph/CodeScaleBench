```python
"""
PulseStream Nexus – Streaming Enrichment Module
-----------------------------------------------

src/module_24.py

This module is responsible for:

1. Consuming raw social-network events from a Kafka topic.
2. Validating each event against a JSONSchema contract.
3. Enriching the event through a configurable Strategy pattern
   (sentiment, toxicity, virality, etc.).
4. Publishing the enriched, validated payload to the next Kafka topic.
5. Exposing Prometheus metrics for observability.

The code purposefully avoids tight coupling with framework or I/O details
and can therefore be unit-tested in isolation.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

import jsonschema
from confluent_kafka import Consumer, Producer, KafkaError, Message
from prometheus_client import Counter, Histogram, start_http_server

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime configuration for the enrichment pipeline."""
    bootstrap_servers: str
    input_topic: str
    output_topic: str
    group_id: str = "pulsestream-enrichment"
    schema_path: Path = Path("schemas/social_event.json")
    latency_histogram_buckets: Sequence[float] = field(
        default_factory=lambda: (
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            float("inf"),
        )
    )
    enrichment_strategies: Sequence[str] = field(
        default_factory=lambda: ("sentiment", "toxicity")
    )
    prometheus_port: int = 9102
    consumer_poll_timeout: float = 1.0  # seconds
    producer_flush_timeout: float = 5.0  # seconds

    @staticmethod
    def from_env() -> "PipelineConfig":
        """Load configuration from environment variables."""
        return PipelineConfig(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
            input_topic=os.getenv("KAFKA_INPUT_TOPIC", "raw_social_events"),
            output_topic=os.getenv("KAFKA_OUTPUT_TOPIC", "enriched_social_events"),
            group_id=os.getenv("KAFKA_GROUP_ID", "pulsestream-enrichment"),
            schema_path=Path(
                os.getenv("EVENT_SCHEMA_PATH", "schemas/social_event.json")
            ),
            prometheus_port=int(os.getenv("PROM_PORT", "9102")),
        )


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

METRICS_NAMESPACE = "pulsestream"

MESSAGES_PROCESSED = Counter(
    name="messages_processed_total",
    documentation="Total number of social events processed.",
    namespace=METRICS_NAMESPACE,
)

MESSAGES_INVALID = Counter(
    name="messages_invalid_total",
    documentation="Number of events rejected due to schema validation errors.",
    namespace=METRICS_NAMESPACE,
)

LATENCY_HISTOGRAM = Histogram(
    name="processing_latency_seconds",
    documentation="Latency for processing a single event.",
    namespace=METRICS_NAMESPACE,
    buckets=PipelineConfig().latency_histogram_buckets,  # type: ignore[misc]
)


# --------------------------------------------------------------------------- #
# Validation Layer
# --------------------------------------------------------------------------- #


class SchemaValidator:
    """JSONSchema validation façade for social events."""

    def __init__(self, schema_path: Path) -> None:
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        with schema_path.open("r", encoding="utf-8") as fp:
            self._schema: Dict[str, Any] = json.load(fp)

        self._validator = jsonschema.Draft7Validator(self._schema)

    def validate(self, payload: Dict[str, Any]) -> None:
        """Raises jsonschema.ValidationError on failure."""
        self._validator.validate(payload)


# --------------------------------------------------------------------------- #
# Enrichment Strategies
# --------------------------------------------------------------------------- #


class EnrichmentStrategy(ABC):
    """Abstract base class for enrichment strategies."""

    @abstractmethod
    def enrich(self, event: Dict[str, Any]) -> Dict[str, Any]:
        pass


class SentimentEnrichmentStrategy(EnrichmentStrategy):
    """Adds sentiment score using a simple heuristic."""

    def enrich(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text: str = event.get("text") or ""
        score = self._compute_sentiment(text)
        event["sentiment"] = {"score": score}
        return event

    @staticmethod
    def _compute_sentiment(text: str) -> float:
        # Placeholder implementation (replace with ML/NLP model)
        positive_keywords = ("love", "great", "happy", "excellent")
        negative_keywords = ("hate", "bad", "sad", "terrible")
        score = 0.0
        for word in positive_keywords:
            if word in text.lower():
                score += 0.1
        for word in negative_keywords:
            if word in text.lower():
                score -= 0.1
        return max(min(score, 1.0), -1.0)


class ToxicityEnrichmentStrategy(EnrichmentStrategy):
    """Flags toxic language using keyword blacklist (placeholder)."""

    _blacklist = {"idiot", "stupid", "dumb"}

    def enrich(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text: str = event.get("text") or ""
        toxic = any(word in text.lower() for word in self._blacklist)
        event["toxicity"] = {"toxic": toxic}
        return event


# --------------------------------------------------------------------------- #
# Pipeline Orchestrator
# --------------------------------------------------------------------------- #


class EnrichmentPipeline:
    """
    Combines schema validation with a chain of enrichment strategies.
    """

    def __init__(self, validator: SchemaValidator, strategies: List[EnrichmentStrategy]):
        self._validator = validator
        self._strategies = strategies

    def run(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and enrich the event.

        Raises
        ------
        jsonschema.ValidationError
            If the input event does not conform to the schema.
        """
        # Validate
        self._validator.validate(event)

        # Enrich
        for strategy in self._strategies:
            event = strategy.enrich(event)

        return event


# --------------------------------------------------------------------------- #
# Kafka Stream Processor
# --------------------------------------------------------------------------- #


class KafkaStreamProcessor:
    """
    Consumes events from Kafka, executes the enrichment pipeline,
    and produces the results downstream.
    """

    def __init__(self, cfg: PipelineConfig, pipeline: EnrichmentPipeline) -> None:
        self._cfg = cfg
        self._pipeline = pipeline

        consumer_conf = {
            "bootstrap.servers": cfg.bootstrap_servers,
            "group.id": cfg.group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }

        producer_conf = {
            "bootstrap.servers": cfg.bootstrap_servers,
            "linger.ms": 10,
        }

        self._consumer = Consumer(consumer_conf)
        self._producer = Producer(producer_conf)

        self._running = False

    # -------------------- Consumer Loop -------------------- #

    async def start(self) -> None:
        self._running = True
        self._consumer.subscribe([self._cfg.input_topic])

        loop = asyncio.get_running_loop()
        try:
            while self._running:
                msg: Message | None = self._consumer.poll(
                    timeout=self._cfg.consumer_poll_timeout
                )
                if msg is None:
                    await asyncio.sleep(0)  # yield control
                    continue

                if msg.error():
                    # For production, differentiate retriable errors
                    self._log_kafka_error(msg.error())
                    continue

                await self._process_message(msg)

        finally:
            self._shutdown()

    async def _process_message(self, msg: Message) -> None:
        start_time = time.perf_counter()
        try:
            raw_payload = msg.value().decode("utf-8")
            event = json.loads(raw_payload)

            enriched_event = self._pipeline.run(event)
            self._publish(msg.key(), enriched_event)

            # Manual commit for at-least-once semantics
            self._consumer.commit(asynchronous=False)

            MESSAGES_PROCESSED.inc()

        except (json.JSONDecodeError, jsonschema.ValidationError):
            MESSAGES_INVALID.inc()
            # For malformed events, commit offset to skip them
            self._consumer.commit(asynchronous=False)

        except Exception:
            # Message will be re-processed (no commit); log & propagate
            MESSAGES_INVALID.inc()
            raise

        finally:
            LATENCY_HISTOGRAM.observe(time.perf_counter() - start_time)

    def _publish(self, key: bytes | None, message: Dict[str, Any]) -> None:
        self._producer.produce(
            topic=self._cfg.output_topic,
            key=key,
            value=json.dumps(message).encode("utf-8"),
            on_delivery=self._delivery_report,
        )
        # Try to flush queue without blocking the whole processor
        self._producer.poll(0)

    # -------------------- Utility -------------------- #

    def _shutdown(self) -> None:
        self._running = False
        try:
            self._consumer.close()
        finally:
            # Flush outstanding messages
            self._producer.flush(self._cfg.producer_flush_timeout)

    @staticmethod
    def _log_kafka_error(error: KafkaError) -> None:
        sys.stderr.write(f"[Kafka-Error]: {error}\n")

    @staticmethod
    def _delivery_report(err: KafkaError | None, msg: Message) -> None:
        if err is not None:
            sys.stderr.write(f"[Delivery-Error]: {err}\n")


# --------------------------------------------------------------------------- #
# Strategy Factory
# --------------------------------------------------------------------------- #


def build_strategies(strategy_names: Sequence[str]) -> List[EnrichmentStrategy]:
    registry: Dict[str, EnrichmentStrategy] = {
        "sentiment": SentimentEnrichmentStrategy(),
        "toxicity": ToxicityEnrichmentStrategy(),
    }

    unknown = [s for s in strategy_names if s not in registry]
    if unknown:
        raise ValueError(f"Unknown strategies requested: {unknown}")

    return [registry[name] for name in strategy_names]


# --------------------------------------------------------------------------- #
# Entry-point
# --------------------------------------------------------------------------- #


def _install_signal_handlers(cancel_event: asyncio.Event) -> None:
    def _handler(_sig: int, _frame: Any) -> None:  # noqa: ANN401
        cancel_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)


async def _async_main() -> None:
    cfg = PipelineConfig.from_env()

    # Start Prometheus metrics server *before* processing
    start_http_server(cfg.prometheus_port)

    validator = SchemaValidator(cfg.schema_path)
    strategies = build_strategies(cfg.enrichment_strategies)
    pipeline = EnrichmentPipeline(validator, strategies)
    processor = KafkaStreamProcessor(cfg, pipeline)

    cancel = asyncio.Event()
    _install_signal_handlers(cancel)

    # Run processor until cancellation
    try:
        await asyncio.gather(processor.start(), cancel.wait())
    finally:
        processor._shutdown()  # graceful teardown


def main() -> None:
    """CLI entry point for the enrichment service."""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        # Already handled by signal but ensures clean exit code
        pass


if __name__ == "__main__":
    main()
```