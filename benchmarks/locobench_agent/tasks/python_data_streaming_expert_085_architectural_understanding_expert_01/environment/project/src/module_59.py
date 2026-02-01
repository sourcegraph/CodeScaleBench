```python
"""
PulseStream Nexus
=================

src/module_59.py

This module implements an asynchronous Kafka micro-service that consumes raw
social-network events, validates and enriches them, and republishes the result
to a downstream topic.  It demonstrates several architectural patterns used
across the PulseStream Nexus project:

*  Clean Architecture / Ports & Adapters
*  Strategy Pattern for pluggable transformations
*  Observer Pattern via Prometheus metrics & Sentry error reporting
*  Robust error handling and configurable runtime behaviour

The code is intentionally self-contained so that it can be dropped into a new
service repository and started with minimal ceremony.

Author: pulse-stream@protonmail.com
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from abc import ABC, abstractmethod
from asyncio import Task
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel, Field, ValidationError, root_validator

# --------------------------------------------------------------------------- #
# Optional / soft dependencies
# --------------------------------------------------------------------------- #
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Provide helpful feedback at import-time instead of runtime.
    raise SystemExit(
        "aiokafka is not installed.  Install with:  pip install aiokafka"
    )

try:
    from prometheus_client import start_http_server, Counter, Histogram  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Metrics are optional; degrading gracefully keeps the app runnable in tests.
    Counter = Histogram = None  # type: ignore
    start_http_server = lambda *_args, **_kwargs: None  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging config
# --------------------------------------------------------------------------- #

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("pulse-stream.module_59")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class KafkaConfig:
    """Runtime configuration loaded from environment variables."""

    bootstrap_servers: Sequence[str] = field(
        default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(
            ","
        )
    )
    consume_topic: str = os.getenv("RAW_EVENTS_TOPIC", "social_raw")
    produce_topic: str = os.getenv("ENRICHED_EVENTS_TOPIC", "social_enriched")
    dead_letter_topic: str = os.getenv("DEAD_LETTER_TOPIC", "social_dlq")
    group_id: str = os.getenv("CONSUMER_GROUP_ID", "pulse-stream-enricher")

    # Producer-level
    linger_ms: int = int(os.getenv("PRODUCER_LINGER_MS", "5"))
    compression_type: str = os.getenv("PRODUCER_COMPRESSION", "gzip")


@dataclass(frozen=True)
class ServiceConfig:
    """High-level service configuration."""

    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    metrics_port: int = int(os.getenv("METRICS_PORT", "8000"))
    sentry_dsn: Optional[str] = os.getenv("SENTRY_DSN")
    max_concurrent_tasks: int = int(os.getenv("MAX_CONCURRENT_TASKS", "50"))


CONFIG = ServiceConfig()

# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #


class SocialEvent(BaseModel):
    """
    Canonical representation of an incoming social-network message.

    All networks are collapsed into this shared schema to simplify processing.
    """

    id: str
    network: str = Field(..., description="twitter|reddit|mastodon|discord|...")
    timestamp: int = Field(..., ge=0, description="Unix epoch in milliseconds")
    author_id: str
    text: str = Field(..., min_length=1)
    # Optional metadata fields
    language: Optional[str] = None
    reply_to: Optional[str] = None

    # Enrichment fields
    sentiment: Optional[float] = None
    toxicity: Optional[float] = None
    virality: Optional[float] = None

    @root_validator
    def _sanitize_network(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        network = values.get("network", "").lower()
        if network not in {"twitter", "reddit", "mastodon", "discord"}:
            raise ValueError(f"Unsupported network: {network}")
        values["network"] = network
        return values


# --------------------------------------------------------------------------- #
# Transformation strategies
# --------------------------------------------------------------------------- #


class TransformationStrategy(ABC):
    """Interface for pluggable event transformations."""

    @abstractmethod
    async def apply(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        """Apply the transformation to the given event."""


class SentimentAnalysisStrategy(TransformationStrategy):
    """
    Naïve sentiment implementation.

    NOTE: In production we would call an external ML model.  Here we simply
    assign a pseudo-random sentiment based on hash(text).
    """

    async def apply(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        text_hash = hash(event.text) % 100
        event.sentiment = (text_hash - 50) / 50  # range ≈ [-1.0, 1.0]
        return event


class ToxicityDetectionStrategy(TransformationStrategy):
    """
    Naïve toxicity score based on banned word count.

    Real deployment would leverage a Transformer model or Perspective API.
    """

    _BANNED_WORDS = {"hate", "idiot", "kill", "stupid"}

    async def apply(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        lowered = event.text.lower()
        count = sum(word in lowered for word in self._BANNED_WORDS)
        event.toxicity = min(count / len(self._BANNED_WORDS), 1.0)
        return event


class ViralityScoreStrategy(TransformationStrategy):
    """
    Estimate virality based on presence of hashtags and mentions.

    Placeholder logic until we have real engagement data.
    """

    async def apply(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        hashtags = event.text.count("#")
        mentions = event.text.count("@")
        event.virality = min((hashtags + mentions) / 10.0, 1.0)
        return event


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

if Counter and Histogram:
    METRICS = {
        "msg_consumed": Counter(
            "psn_msg_consumed_total",
            "Total Kafka messages consumed",
            ["topic"],
        ),
        "msg_produced": Counter(
            "psn_msg_produced_total",
            "Total Kafka messages produced",
            ["topic"],
        ),
        "msg_failed": Counter(
            "psn_msg_failed_total",
            "Total messages sent to dead-letter queue",
            ["error_type"],
        ),
        "latency": Histogram(
            "psn_processing_latency_seconds",
            "End-to-end event processing latency",
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5),
        ),
    }
else:  # pragma: no cover
    METRICS = {key: None for key in ("msg_consumed", "msg_produced", "msg_failed", "latency")}

# --------------------------------------------------------------------------- #
# Service implementation
# --------------------------------------------------------------------------- #


class DataStreamProcessor:
    """
    Top-level orchestrator: consume, validate, enrich, publish.
    """

    def __init__(
        self,
        *,
        config: ServiceConfig = CONFIG,
        strategies: Optional[Sequence[TransformationStrategy]] = None,
    ) -> None:
        self.config = config
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._running = asyncio.Event()
        self._tasks: List[Task] = []
        self._strategies: Sequence[TransformationStrategy] = strategies or [
            SentimentAnalysisStrategy(),
            ToxicityDetectionStrategy(),
            ViralityScoreStrategy(),
        ]

    # --------------------------------------------------------------------- #
    # Life-cycle
    # --------------------------------------------------------------------- #

    async def start(self) -> None:
        """Create Kafka clients and begin consuming."""
        logger.info("Starting DataStreamProcessor")
        await self._setup_instrumentation()

        self._consumer = AIOKafkaConsumer(
            self.config.kafka.consume_topic,
            bootstrap_servers=self.config.kafka.bootstrap_servers,
            group_id=self.config.kafka.group_id,
            enable_auto_commit=False,
            value_deserializer=lambda x: x,  # raw bytes
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.config.kafka.bootstrap_servers,
            linger_ms=self.config.kafka.linger_ms,
            compression_type=self.config.kafka.compression_type,
        )

        await self._producer.start()
        await self._consumer.start()
        self._running.set()

        # Kick off the main event loop
        self._tasks.append(asyncio.create_task(self._consume_loop()))

    async def _setup_instrumentation(self) -> None:
        if sentry_sdk and self.config.sentry_dsn:
            sentry_sdk.init(dsn=self.config.sentry_dsn)
            logger.info("Sentry initialised")
        if start_http_server and Counter:  # pylint: disable=used-before-assignment
            start_http_server(self.config.metrics_port)
            logger.info("Prometheus metrics exporter bound to :%s", self.config.metrics_port)

    async def stop(self, *_args: Any) -> None:
        """Gracefully shut down Kafka clients."""
        logger.info("Stopping DataStreamProcessor")
        self._running.clear()

        # Cancel outstanding tasks
        for task in self._tasks:
            task.cancel()

        # Close Kafka clients
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    # --------------------------------------------------------------------- #
    # Main consume / process / produce loop
    # --------------------------------------------------------------------- #

    async def _consume_loop(self) -> None:
        assert self._consumer and self._producer  # mypy
        backpressure_sem = asyncio.Semaphore(self.config.max_concurrent_tasks)
        logger.info(
            "Consume loop started: topic=%s -> %s",
            self.config.kafka.consume_topic,
            self.config.kafka.produce_topic,
        )

        try:
            async for msg in self._consumer:
                if METRICS["msg_consumed"]:
                    METRICS["msg_consumed"].labels(self.config.kafka.consume_topic).inc()

                await backpressure_sem.acquire()
                task = asyncio.create_task(
                    self._handle_message(msg.value, backpressure_sem)
                )
                self._tasks.append(task)
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("Consume loop cancelled")
        finally:
            logger.info("Consume loop exited")

    async def _handle_message(self, raw_value: bytes, semaphore: asyncio.Semaphore) -> None:
        start_ts = asyncio.get_event_loop().time()

        try:
            # -------------------- Validation -------------------- #
            try:
                payload = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid_json") from exc

            try:
                event = SocialEvent.parse_obj(payload)
            except ValidationError as exc:
                raise ValueError("schema_validation_failed") from exc

            # ------------------ Transformations ------------------ #
            for strat in self._strategies:
                event = await strat.apply(event)

            # ----------------------- Output ---------------------- #
            await self._producer.send_and_wait(
                topic=self.config.kafka.produce_topic,
                value=json.dumps(event.dict()).encode(),
            )

            # Manual offset commit ­— safe after produce success
            if self._consumer and self._consumer._commit_offset_on_assign:  # type: ignore
                await self._consumer.commit()

            # Metrics
            proc_time = asyncio.get_event_loop().time() - start_ts
            if METRICS["latency"]:
                METRICS["latency"].observe(proc_time)
            if METRICS["msg_produced"]:
                METRICS["msg_produced"].labels(self.config.kafka.produce_topic).inc()

        except Exception as err:  # pylint: disable=broad-except
            await self._handle_failure(raw_value, err)
        finally:
            semaphore.release()

    async def _handle_failure(self, raw_value: bytes, exc: Exception) -> None:
        """
        Push the offending message to DLQ and surface the error.
        """
        err_type = type(exc).__name__
        logger.exception("Processing failure [%s]: %s", err_type, exc, exc_info=exc)

        # Metrics
        if METRICS["msg_failed"]:
            METRICS["msg_failed"].labels(err_type).inc()

        if sentry_sdk:
            sentry_sdk.capture_exception(exc)

        # Attempt DLQ publish ‑- swallow errors to avoid infinite loops
        try:
            assert self._producer
            await self._producer.send_and_wait(
                topic=self.config.kafka.dead_letter_topic,
                value=raw_value,
            )
        except Exception as dlq_err:  # pylint: disable=broad-except
            logger.error("Failed to publish message to DLQ: %s", dlq_err, exc_info=dlq_err)

    # --------------------------------------------------------------------- #
    # CLI entry-point
    # --------------------------------------------------------------------- #

    @classmethod
    def run_forever(cls) -> None:  # pragma: no cover
        """Entry-point when invoked as a standalone service."""
        processor = cls()

        loop = asyncio.get_event_loop()

        # Graceful shutdown on SIGINT/SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, partial(asyncio.create_task, processor.stop()))

        try:
            loop.run_until_complete(processor.start())
            loop.run_forever()
        finally:
            logger.info("Event-loop shutting down")
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()


# --------------------------------------------------------------------------- #
# executable script helper
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    DataStreamProcessor.run_forever()
```