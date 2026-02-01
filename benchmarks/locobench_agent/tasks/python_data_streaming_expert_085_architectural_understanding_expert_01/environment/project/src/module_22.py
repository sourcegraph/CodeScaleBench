```python
"""
module_22.py
PulseStream Nexus – Real-time Kafka ingestion & enrichment service.

This module contains a high-level, production-ready worker that
  • consumes social events from a Kafka topic,
  • validates the raw payload against an internal pydantic schema
    (optionally additionally against a Great Expectations suite),
  • enriches the event with sentiment / toxicity scores using the
    Strategy pattern,
  • notifies downstream observers, and
  • exposes Prometheus metrics for operational insight.

The implementation purposefully keeps hard I/O (Kafka, GE stores, network)
behind abstraction layers to preserve Clean Architecture boundaries.
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
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, Dict, List, MutableMapping, Optional

from aiokafka import AIOKafkaConsumer  # type: ignore
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from pydantic import BaseModel, ValidationError, validator

# ------------------------------------------------------------------------------
# Logging configuration
# ------------------------------------------------------------------------------

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
)
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format=_LOG_FORMAT,
)
logger = logging.getLogger("pulsestream.module_22")

# ------------------------------------------------------------------------------
# Domain model & validation
# ------------------------------------------------------------------------------


class SocialEvent(BaseModel):
    """
    Canonical representation of an incoming social interaction.
    """

    event_id: str
    network: str
    user_id: str
    content: str
    timestamp: float

    # Custom validators --------------------------------------------------------
    @validator("network")
    def _network_must_be_supported(cls, v: str) -> str:
        allowed = {"twitter", "reddit", "mastodon", "discord", "x"}
        if v.lower() not in allowed:
            raise ValueError(f"Unsupported network '{v}'.")
        return v.lower()

    @validator("timestamp")
    def _timestamp_must_be_reasonable(cls, v: float) -> float:
        # Reject timestamps more than 24h into the future.
        now = time.time()
        if v - now > 3600 * 24:
            raise ValueError("Timestamp appears to be unrealistically in the future.")
        return v


# ------------------------------------------------------------------------------
# Strategy Pattern ‑ Sentiment / Toxicity
# ------------------------------------------------------------------------------


class EnrichmentStrategy(ABC):
    """
    Strategy interface for message enrichment.
    """

    @abstractmethod
    async def enrich(self, event: SocialEvent) -> MutableMapping[str, Any]:
        raise NotImplementedError


class SentimentAnalysisStrategy(EnrichmentStrategy):
    """
    Simple rule-based sentiment analysis placeholder.

    In production, this would call a ML model or external microservice.
    """

    async def enrich(self, event: SocialEvent) -> MutableMapping[str, Any]:
        content = event.content.lower()
        score = 0.0
        if any(word in content for word in ("love", "great", "awesome")):
            score = 0.8
        elif any(word in content for word in ("hate", "terrible", "bad")):
            score = -0.8
        logger.debug("Sentiment score for %s computed: %s", event.event_id, score)
        return {"sentiment_score": score}


class ToxicityAnalysisStrategy(EnrichmentStrategy):
    """
    Naïve toxicity detection.

    Replace with advanced models (e.g. Perspective API) when available.
    """

    async def enrich(self, event: SocialEvent) -> MutableMapping[str, Any]:
        tokens = set(event.content.lower().split())
        toxic_cues = {"idiot", "stupid", "dumb"}
        toxicity = 1.0 if tokens & toxic_cues else 0.0
        logger.debug("Toxicity score for %s computed: %s", event.event_id, toxicity)
        return {"toxicity_score": toxicity}


# ------------------------------------------------------------------------------
# Observer Pattern ‑ downstream notification
# ------------------------------------------------------------------------------


class Observer(ABC):
    """
    Generic Observer interface.
    """

    @abstractmethod
    async def notify(self, event: Dict[str, Any]) -> None: ...


class PrintObserver(Observer):
    """
    Trivial observer that logs the enriched event.
    """

    async def notify(self, event: Dict[str, Any]) -> None:
        logger.info("Processed event: %s", json.dumps(event)[:500])


# ------------------------------------------------------------------------------
# Great Expectations integration
# ------------------------------------------------------------------------------

try:
    import great_expectations as ge  # type: ignore
except ModuleNotFoundError:  # Allow running w/o GE installed.
    ge = None  # type: ignore

# ------------------------------------------------------------------------------
# Prometheus metrics
# ------------------------------------------------------------------------------

_METRIC_INGESTED: Counter = Counter(
    "psn_ingested_messages_total",
    "Number of raw messages ingested from Kafka",
    ["topic"],
)
_METRIC_PROCESSED: Counter = Counter(
    "psn_processed_messages_total",
    "Number of messages successfully processed",
    ["topic"],
)
_METRIC_FAILED: Counter = Counter(
    "psn_failed_messages_total",
    "Number of messages that failed validation or processing",
    ["topic", "stage"],
)
_METRIC_LATENCY: Histogram = Histogram(
    "psn_processing_latency_seconds",
    "End-to-end latency between Kafka receipt and processing completion",
    ["topic"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
_METRIC_CONSUMER_LAG: Gauge = Gauge(
    "psn_kafka_consumer_lag", "Current consumer lag for the partition", ["topic"]
)

# ------------------------------------------------------------------------------
# Worker implementation
# ------------------------------------------------------------------------------


@dataclass(slots=True)
class WorkerConfig:
    bootstrap_servers: str
    topic: str
    group_id: str = "pulsestream_ingestor"
    commit_interval_ms: int = 5_000
    enable_ge_validation: bool = False
    prometheus_port: int = 8000
    enrichment_strategies: Optional[List[EnrichmentStrategy]] = None
    observers: Optional[List[Observer]] = None
    max_concurrency: int = 8  # process messages concurrently


class StreamIngestionWorker:
    """
    High-level orchestrator that wires together: Kafka ⟶ Validation ⟶ Enrichment ⟶ Observers
    """

    def __init__(self, cfg: WorkerConfig) -> None:
        self._cfg = cfg
        self._consumer: Optional[AIOKafkaConsumer] = None
        # Provide sane defaults
        self._strategies = cfg.enrichment_strategies or [
            SentimentAnalysisStrategy(),
            ToxicityAnalysisStrategy(),
        ]
        self._observers = cfg.observers or [PrintObserver()]

        self._running = False
        self._task_group: Optional[asyncio.TaskGroup] = None

        # Start Prometheus server early.
        start_http_server(self._cfg.prometheus_port)
        logger.info("Prometheus exporter launched on :%d", self._cfg.prometheus_port)

    # ------------------------------------------------------------------
    # Kafka bootstrap & shutdown helpers
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "StreamIngestionWorker":
        await self._bootstrap_consumer()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._shutdown()

    async def _bootstrap_consumer(self) -> None:
        logger.info("Bootstrapping Kafka consumer for topic '%s'...", self._cfg.topic)
        consumer = AIOKafkaConsumer(
            self._cfg.topic,
            bootstrap_servers=self._cfg.bootstrap_servers.split(","),
            group_id=self._cfg.group_id,
            enable_auto_commit=True,
            auto_commit_interval_ms=self._cfg.commit_interval_ms,
            value_deserializer=lambda m: m.decode("utf-8"),
        )
        await consumer.start()
        self._consumer = consumer
        logger.info("Kafka consumer ready (group_id=%s).", self._cfg.group_id)

    async def _shutdown(self) -> None:
        self._running = False
        if self._task_group:
            self._task_group.cancel()
            with suppress(asyncio.CancelledError):
                await self._task_group
        if self._consumer:
            await self._consumer.stop()
        logger.info("Worker shut down complete.")

    # ------------------------------------------------------------------
    # Core run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        if not self._consumer:
            raise RuntimeError("Consumer not bootstrapped. Use 'async with' context.")

        self._running = True
        logger.info("Worker is running. Waiting for messages …")

        async with asyncio.TaskGroup() as tg:
            self._task_group = tg
            # Spawn a bounded-semaphore worker pool.
            sem = asyncio.Semaphore(self._cfg.max_concurrency)
            while self._running:
                try:
                    msg = await self._consumer.getone()
                except asyncio.CancelledError:
                    break

                _METRIC_INGESTED.labels(self._cfg.topic).inc()
                await sem.acquire()
                tg.create_task(
                    self._handle_message(msg.value, sem),
                    name=f"proc-{msg.partition}-{msg.offset}",
                )

    # ------------------------------------------------------------------
    # Individual message flow
    # ------------------------------------------------------------------

    async def _handle_message(self, payload: str, sem: asyncio.Semaphore) -> None:
        """
        Handle a single raw message. Releases semaphore upon completion.
        """
        start_time = time.time()
        try:
            await self._process(payload)
            _METRIC_PROCESSED.labels(self._cfg.topic).inc()
        except Exception as exc:
            logger.exception("Failed to handle message: %s", exc)
            _METRIC_FAILED.labels(self._cfg.topic, "processing").inc()
        finally:
            latency = time.time() - start_time
            _METRIC_LATENCY.labels(self._cfg.topic).observe(latency)
            sem.release()

    async def _process(self, raw_message: str) -> None:
        # 1. Parse JSON
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError as e:
            logger.warning("JSON decode error: %s", e)
            _METRIC_FAILED.labels(self._cfg.topic, "json_decode").inc()
            return

        # 2. Pydantic validation
        try:
            event = SocialEvent.parse_obj(data)
        except ValidationError as e:
            logger.debug("Schema validation failed: %s", e)
            _METRIC_FAILED.labels(self._cfg.topic, "schema_validation").inc()
            return

        # 3. Optional Great Expectations validation
        if self._cfg.enable_ge_validation and ge is not None:
            if not self._expect_ge_passes(data):
                _METRIC_FAILED.labels(self._cfg.topic, "ge_validation").inc()
                return

        # 4. Enrichment pipeline
        enriched: Dict[str, Any] = event.dict()
        for strategy in self._strategies:
            try:
                enriched.update(await strategy.enrich(event))
            except Exception as e:
                logger.error(
                    "Enrichment strategy %s failed for %s: %s",
                    strategy.__class__.__name__,
                    event.event_id,
                    e,
                )

        # 5. Notify observers
        await asyncio.gather(*(o.notify(enriched) for o in self._observers))

    # ------------------------------------------------------------------
    # Helper – Great Expectations
    # ------------------------------------------------------------------

    @staticmethod
    def _expect_ge_passes(data: Dict[str, Any]) -> bool:
        if ge is None:
            logger.warning("Great Expectations not available; skipping checks.")
            return True

        df = ge.dataset.PandasDataset.from_dict({k: [v] for k, v in data.items()})
        expectations = [
            ("expect_column_values_to_not_be_null", dict(column="event_id")),
            ("expect_column_values_to_not_be_null", dict(column="content")),
            ("expect_column_values_to_match_regex", dict(column="event_id", regex=r"^\w+$")),
        ]
        for method, kwargs in expectations:
            if not getattr(df, method)(**kwargs).success:
                logger.debug("GE expectation %s failed: %s", method, kwargs)
                return False
        return True


# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------


async def _run_worker() -> None:
    cfg = WorkerConfig(
        bootstrap_servers=os.getenv("PULSENEXUS_KAFKA_BROKERS", "localhost:9092"),
        topic=os.getenv("PULSENEXUS_TOPIC", "social_events"),
        group_id=os.getenv("PULSENEXUS_CONSUMER_GROUP", "psn_ingestor"),
        enable_ge_validation=bool(int(os.getenv("PULSENEXUS_GE_VALIDATION", "0"))),
        prometheus_port=int(os.getenv("PULSENEXUS_PROM_PORT", "8000")),
    )

    async with StreamIngestionWorker(cfg) as worker:

        # Graceful shutdown handling -----------------------------------------
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_signal(sig: signal.Signals) -> None:
            logger.info("Received %s, initiating shutdown…", sig.name)
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, _handle_signal, sig)

        await asyncio.gather(worker.run(), stop_event.wait())

        # After stop_event triggered, worker context manager will clean up.


def main() -> None:
    """
    Run via: `python -m src.module_22`
    """
    try:
        asyncio.run(_run_worker())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, exiting…")


if __name__ == "__main__":
    main()
```