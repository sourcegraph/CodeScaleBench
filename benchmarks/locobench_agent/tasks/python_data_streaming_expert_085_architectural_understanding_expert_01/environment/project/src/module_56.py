```python
"""
PulseStream Nexus – Data Streaming Platform
-------------------------------------------

src/module_56.py

This module hosts production-grade, asyncio-driven Kafka consumer utilities
designed for PulseStream Nexus.

Highlights
~~~~~~~~~~
* Clean-architecture friendly: business logic is encapsulated behind the
  `ProcessorStrategy` interface.
* Async Kafka layer powered by `aiokafka`.
* Opt-in Sentry error reporting via the `SENTRY_DSN` environment variable.
* Prometheus metrics exported through the default registry.
* Built-in token-bucket rate-limiter to prevent downstream overload.
* Pydantic validation of raw events for early data-quality feedback.

Author: PulseStream Core Team
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
from typing import Any, List, Optional

from aiokafka import AIOKafkaConsumer, ConsumerRecord  # type: ignore
from pydantic import BaseModel, ValidationError  # type: ignore
from prometheus_client import Counter, Histogram, start_http_server  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

__all__ = [
    "Event",
    "ProcessorStrategy",
    "CompositeStrategy",
    "SentimentEnrichmentStrategy",
    "ToxicityEnrichmentStrategy",
    "TokenBucketRateLimiter",
    "RateLimitedKafkaConsumer",
    "run_consumer",
]

# --------------------------------------------------------------------------- #
# Configuration & Logging                                                     #
# --------------------------------------------------------------------------- #

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    stream=sys.stdout,
    level=_LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("pulse.module_56")

# --------------------------------------------------------------------------- #
# Sentry Initialization (optional)                                            #
# --------------------------------------------------------------------------- #

if (dsn := os.getenv("SENTRY_DSN")) and sentry_sdk is not None:
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENV", "development"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
    )
    logger.info("Sentry initialised.")
else:
    logger.info("Sentry DSN not provided. Error reporting disabled.")

# --------------------------------------------------------------------------- #
# Prometheus Metrics                                                          #
# --------------------------------------------------------------------------- #

EVENT_INGESTED = Counter(
    "ps_event_ingested_total",
    "Total number of events ingested from Kafka.",
)
EVENT_PROCESSED = Counter(
    "ps_event_processed_total",
    "Total number of events successfully processed by strategies.",
)
EVENT_FAILED = Counter(
    "ps_event_failed_total",
    "Total number of events that failed processing.",
)
PROCESS_LATENCY = Histogram(
    "ps_event_process_latency_seconds",
    "Latency observed while processing downstream strategies.",
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
        10,
    ),
)

_METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
start_http_server(_METRICS_PORT)
logger.info("Prometheus metrics exporter launched on port %s", _METRICS_PORT)

# --------------------------------------------------------------------------- #
# Data Models                                                                 #
# --------------------------------------------------------------------------- #


class Event(BaseModel):
    """Public model representing a social-network event."""

    event_id: str
    payload: dict[str, Any]
    source: str
    created_at: float

    class Config:
        allow_mutation = False
        frozen = True


# --------------------------------------------------------------------------- #
# Strategy Interfaces                                                         #
# --------------------------------------------------------------------------- #


class ProcessorStrategy(ABC):
    """Async strategy contract for event processing."""

    @abstractmethod
    async def process(self, event: Event) -> None:  # pragma: no cover
        """Execute transformation or enrichment on the event."""
        raise NotImplementedError


class CompositeStrategy(ProcessorStrategy):
    """
    Compose several strategies sequentially.

    Useful for layering diverse enrichments while remaining
    compliant with the single-responsibility principle.
    """

    def __init__(self, strategies: List[ProcessorStrategy]) -> None:
        self._strategies = strategies

    async def process(self, event: Event) -> None:
        for strat in self._strategies:
            await strat.process(event)


# --------------------------------------------------------------------------- #
# Example Strategies                                                          #
# --------------------------------------------------------------------------- #


class SentimentEnrichmentStrategy(ProcessorStrategy):
    """
    Dummy sentiment analysis strategy.

    Replace with the real inference call to your sentiment model.
    """

    async def process(self, event: Event) -> None:
        # Simulate network call latency
        await asyncio.sleep(0.005)
        sentiment_score = hash(event.event_id) % 3 - 1  # simplistic placeholder
        logger.debug("Sentiment for %s: %s", event.event_id, sentiment_score)
        # Tag result into some downstream sink or event bus here.


class ToxicityEnrichmentStrategy(ProcessorStrategy):
    """
    Dummy toxicity detection strategy.

    Replace with the real toxicity classifier inference.
    """

    async def process(self, event: Event) -> None:
        await asyncio.sleep(0.003)
        toxicity = "toxic" if "!!" in json.dumps(event.payload) else "clean"
        logger.debug("Toxicity for %s: %s", event.event_id, toxicity)
        # Persist outcome accordingly.


# --------------------------------------------------------------------------- #
# Rate Limiting                                                               #
# --------------------------------------------------------------------------- #


class TokenBucketRateLimiter:
    """
    Token-bucket rate-limiter suitable for asyncio workflows.

    Attributes
    ----------
    capacity:
        Maximum burst size.
    refill_rate:
        Tokens added per second.
    """

    __slots__ = ("capacity", "refill_rate", "_tokens", "_last_refill")

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        refill_amount = elapsed * self.refill_rate
        if refill_amount > 0:
            self._tokens = min(self.capacity, self._tokens + refill_amount)

    async def acquire(self) -> None:
        """Wait until at least one token is available."""
        while True:
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                return
            await asyncio.sleep(0.001)


# --------------------------------------------------------------------------- #
# Kafka Consumer                                                              #
# --------------------------------------------------------------------------- #


class RateLimitedKafkaConsumer:
    """
    Encapsulates an `aiokafka` consumer with built-in backpressure control.

    Parameters
    ----------
    topic:
        Kafka topic to subscribe to.
    bootstrap_servers:
        Kafka bootstrap servers.
    group_id:
        Consumer group identifier.
    strategy:
        `ProcessorStrategy` used to process each event.
    rate_limiter:
        Optional `TokenBucketRateLimiter`. If `None`, no rate limiting is applied.
    """

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str | list[str] | tuple[str, ...],
        *,
        group_id: str = "psn-default-group",
        strategy: ProcessorStrategy,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        enable_auto_commit: bool = False,
        max_poll_records: int = 500,
    ) -> None:
        self._consumer = AIOKafkaConsumer(
            topic,
            loop=asyncio.get_event_loop(),
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=enable_auto_commit,
            max_poll_records=max_poll_records,
            value_deserializer=lambda b: b.decode("utf-8"),
        )
        self._strategy = strategy
        self._rate_limiter = rate_limiter
        self._running = False

    async def __aenter__(self) -> "RateLimitedKafkaConsumer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        await self.stop()

    async def start(self) -> None:
        await self._consumer.start()
        self._running = True
        logger.info("Kafka consumer started for topic '%s'.", self._consumer._topics)

    async def stop(self) -> None:
        self._running = False
        await self._consumer.stop()
        logger.info("Kafka consumer stopped.")

    async def _handle_record(self, record: ConsumerRecord) -> None:
        EVENT_INGESTED.inc()
        try:
            raw = json.loads(record.value)
            event = Event.parse_obj(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            EVENT_FAILED.inc()
            logger.error("Invalid message skipped (offset %s): %s", record.offset, exc)
            if sentry_sdk is not None:
                sentry_sdk.capture_exception(exc)
            return

        try:
            with PROCESS_LATENCY.time():
                await self._strategy.process(event)
            EVENT_PROCESSED.inc()
        except Exception as exc:  # pragma: no cover
            EVENT_FAILED.inc()
            logger.exception("Processing failure for event %s", event.event_id)
            if sentry_sdk is not None:
                sentry_sdk.capture_exception(exc)

    async def consume(self) -> None:
        """Main loop section. Use `await consumer.consume()`."""
        if not self._running:
            raise RuntimeError("Consumer not started. Call 'start()' first.")

        async for record in self._consumer:  # type: ignore[attr-defined]
            if self._rate_limiter:
                await self._rate_limiter.acquire()

            await self._handle_record(record)
            # Manual commit to ensure "at least once" semantics
            await self._consumer.commit()


# --------------------------------------------------------------------------- #
# Convenience Entrypoint                                                      #
# --------------------------------------------------------------------------- #


async def _shutdown(
    consumer: RateLimitedKafkaConsumer, stop_event: asyncio.Event
) -> None:
    """SIGTERM/SIGINT handler to gracefully shut down the consumer."""
    logger.info("Shutdown signal received. Terminating consumer...")
    await consumer.stop()
    stop_event.set()


def run_consumer() -> None:
    """
    Bootstraps the Kafka consumer with example strategies.

    Environment Variables
    ---------------------
    * KAFKA_BOOTSTRAP           - Comma separated list of brokers.
    * KAFKA_TOPIC               - Topic to subscribe to.
    * KAFKA_GROUP_ID            - Consumer group.
    * RATE_LIMIT_QPS            - Requests per second (float).
    * RATE_LIMIT_BURST          - Optional, default same as QPS.
    """
    brokers = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092").split(",")
    topic = os.getenv("KAFKA_TOPIC", "pulse-events")
    group_id = os.getenv("KAFKA_GROUP_ID", "pulse-group")

    qps = float(os.getenv("RATE_LIMIT_QPS", "200.0"))
    burst = float(os.getenv("RATE_LIMIT_BURST", qps))
    rate_limiter = TokenBucketRateLimiter(capacity=int(burst), refill_rate=qps)

    # Compose strategies
    strategy: ProcessorStrategy = CompositeStrategy(
        [
            SentimentEnrichmentStrategy(),
            ToxicityEnrichmentStrategy(),
        ]
    )

    consumer = RateLimitedKafkaConsumer(
        topic,
        brokers,
        group_id=group_id,
        strategy=strategy,
        rate_limiter=rate_limiter,
    )

    stop_event = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(
            signal.SIGTERM,
            lambda: asyncio.create_task(_shutdown(consumer, stop_event)),
        )
        loop.add_signal_handler(
            signal.SIGINT,
            lambda: asyncio.create_task(_shutdown(consumer, stop_event)),
        )

        async with consumer:
            consumer_task = asyncio.create_task(consumer.consume())
            await stop_event.wait()
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

    import contextlib

    asyncio.run(_main())


# --------------------------------------------------------------------------- #
# CLI Entrypoint                                                              #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    try:
        run_consumer()
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("Interrupted by user.")
```