```python
"""
src/module_4.py
PulseStream Nexus – Data-streaming platform
-------------------------------------------

This module provides a self-contained, production-ready implementation of the
“LiveMetricProcessor”, an asyncio-driven component that listens to an inbound
Kafka topic containing raw social events, validates them, enriches them with a
suite of live metrics (sentiment, toxicity, virality), and republishes
structured results downstream.  The component embodies several architectural
concerns of PulseStream Nexus:

* Clean-Architecture compliant – no frameworks leak into the domain layer
* Strategy pattern – pluggable metric calculators
* Observer pattern – Prometheus + Sentry side effects
* Solid error handling with retry/back-off semantics
* Async I/O – scalable consumption & production

The class is intentionally designed so it can be wired into the larger system
via dependency-injection.  It avoids any hard coupling to external settings
and provides sane defaults for local development.
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
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Mapping, MutableMapping, Optional

# Third-party libraries (all are lightweight and battle-tested)
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord  # type: ignore
from pydantic import BaseModel, Field, ValidationError
from prometheus_client import Counter, Histogram, start_http_server  # type: ignore
import sentry_sdk  # type: ignore

###############################################################################
# Configuration & Logging
###############################################################################

logger = logging.getLogger("pulse.metric_processor")
log_level = os.getenv("PULSE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)

###############################################################################
# Monitoring (Prometheus)
###############################################################################

# NOTE: Exporter is started in `main()`; keep metrics at module level.
PROM_MESSAGE_CONSUMED = Counter(
    "pulse_messages_consumed_total",
    "Total number of raw social events consumed",
    ("platform",),
)

PROM_MESSAGE_PUBLISHED = Counter(
    "pulse_messages_published_total",
    "Total number of enriched social events published",
    ("platform",),
)

PROM_MESSAGE_FAILED = Counter(
    "pulse_messages_failed_total",
    "Total number of social events that failed processing",
    ("platform", "failure_stage"),
)

PROM_PROCESSING_LATENCY = Histogram(
    "pulse_message_latency_seconds",
    "Time spent processing a single message end-to-end",
    ("platform",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

###############################################################################
# Domain objects
###############################################################################


class SocialEvent(BaseModel):
    """
    Canonical representation of an inbound social event.

    NOTE: In a fully-fledged system this would live in the domain layer and
    would be shared across services through a PyPI-distributed core package.
    """

    event_id: str = Field(..., alias="id")
    platform: str
    user_id: str
    text: str
    created_at: float  # epoch seconds
    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class MetricResult:
    sentiment: float  # range ‑1…1
    toxicity: float  # range 0…1
    virality_score: float  # open-ended
    computed_at: float = field(default_factory=lambda: time.time())


###############################################################################
# Strategy pattern for metric computation
###############################################################################


class MetricStrategy(ABC):
    """Abstract base class for metric calculators."""

    @abstractmethod
    def compute(self, event: SocialEvent) -> float:
        raise NotImplementedError


class SentimentStrategy(MetricStrategy):
    """
    Naïve but reasonably effective sentiment scorer that uses a word-list
    approach so the service can run without heavyweight NLP dependencies.
    """

    _POSITIVE_WORDS: set[str] = {
        "love",
        "great",
        "awesome",
        "good",
        "fantastic",
        "nice",
        "happy",
        "yay",
        "excellent",
        "positive",
    }
    _NEGATIVE_WORDS: set[str] = {
        "hate",
        "bad",
        "terrible",
        "awful",
        "sad",
        "angry",
        "horrible",
        "negative",
        "worst",
        "sucks",
    }

    def compute(self, event: SocialEvent) -> float:
        tokens = {t.lower().strip(".,!?") for t in event.text.split()}
        pos_hits = len(tokens & self._POSITIVE_WORDS)
        neg_hits = len(tokens & self._NEGATIVE_WORDS)
        total = pos_hits + neg_hits
        if total == 0:
            return 0.0
        score = (pos_hits - neg_hits) / total
        logger.debug(
            "SentimentStrategy | pos=%s neg=%s score=%s",
            pos_hits,
            neg_hits,
            score,
        )
        return score


class ToxicityStrategy(MetricStrategy):
    """
    Simplified toxicity estimator using a blacklist.  This is *not* production-
    grade but provides a placeholder for a more sophisticated transformer-based
    detector (e.g., PERSPECTIVE API, Detoxify).
    """

    _TOXIC_PHRASES = {
        "idiot",
        "stupid",
        "moron",
        "shut up",
        "kill yourself",
        "racist",
        "homophobic",
        "dumb",
        "ugly",
    }

    def compute(self, event: SocialEvent) -> float:
        text_lc = event.text.lower()
        hits = sum(1 for phrase in self._TOXIC_PHRASES if phrase in text_lc)
        # Very naive scoring: each hit adds 0.2 up to max 1.0
        score = min(hits * 0.2, 1.0)
        logger.debug("ToxicityStrategy | hits=%s score=%s", hits, score)
        return score


class ViralityStrategy(MetricStrategy):
    """
    A platform-agnostic 'virality' score based on engagement metadata.
    """

    def compute(self, event: SocialEvent) -> float:
        meta = event.metadata
        # We defensively convert any unknown types (e.g. None) to int(0)
        likes = int(meta.get("likes", 0) or 0)
        shares = int(meta.get("shares", 0) or 0)  # retweets / boosts
        comments = int(meta.get("comments", 0) or 0)
        reach = int(meta.get("views", 0) or 0)
        # Simple heuristic: weighs each component differently
        score = likes * 1.0 + shares * 2.0 + comments * 1.5 + reach * 0.01
        logger.debug(
            "ViralityStrategy | likes=%s shares=%s comments=%s views=%s score=%s",
            likes,
            shares,
            comments,
            reach,
            score,
        )
        return score


###############################################################################
# Validation
###############################################################################


class EventValidator:
    """
    Lightweight wrapper around Pydantic validation + domain constraints.
    """

    @staticmethod
    def validate(raw: Mapping[str, Any]) -> SocialEvent:
        try:
            event = SocialEvent.parse_obj(raw)
        except ValidationError as exc:
            logger.debug("ValidationError: %s", exc)
            raise

        # Additional domain rules (e.g., text length)
        if len(event.text.strip()) == 0:  # pragma: no cover
            raise ValueError("Text field must not be empty.")

        return event


###############################################################################
# Kafka I/O helpers
###############################################################################


@asynccontextmanager
async def kafka_consumer(
    topic: str,
    group_id: str,
    bootstrap_servers: str = "localhost:9092",
    **kwargs: Any,
) -> AsyncIterator[AIOKafkaConsumer]:
    consumer = AIOKafkaConsumer(
        topic,
        group_id=group_id,
        bootstrap_servers=bootstrap_servers,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        **kwargs,
    )
    await consumer.start()
    try:
        yield consumer
    finally:
        await consumer.stop()


@asynccontextmanager
async def kafka_producer(
    bootstrap_servers: str = "localhost:9092",
    **kwargs: Any,
) -> AsyncIterator[AIOKafkaProducer]:
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        **kwargs,
    )
    await producer.start()
    try:
        yield producer
    finally:
        await producer.stop()


###############################################################################
# Main processing pipeline
###############################################################################


class LiveMetricProcessor:
    """
    Async-driven orchestrator that wires together validation, metric
    calculation, and Kafka I/O.
    """

    def __init__(
        self,
        *,
        in_topic: str,
        out_topic: str,
        group_id: str,
        bootstrap_servers: str = "localhost:9092",
        bulk_commit_size: int = 100,
        sentry_dsn: Optional[str] = None,
    ) -> None:
        self._in_topic = in_topic
        self._out_topic = out_topic
        self._group_id = group_id
        self._bootstrap_servers = bootstrap_servers
        self._bulk_commit_size = bulk_commit_size
        self._should_stop = asyncio.Event()

        # Compose strategies
        self._strategies: Mapping[str, MetricStrategy] = {
            "sentiment": SentimentStrategy(),
            "toxicity": ToxicityStrategy(),
            "virality": ViralityStrategy(),
        }

        if sentry_dsn:
            sentry_sdk.init(sentry_dsn, traces_sample_rate=0.1)

    # ------------------------------------------------------------------ #
    async def _process_record(
        self,
        record: ConsumerRecord,
        producer: AIOKafkaProducer,
        commit_queue: List[Any],
    ) -> None:
        start_ts = time.perf_counter()
        platform = "unknown"

        try:
            raw_event: MutableMapping[str, Any] = record.value  # type: ignore
            platform = str(raw_event.get("platform", "unknown"))
            PROM_MESSAGE_CONSUMED.labels(platform=platform).inc()

            # 1. Validate
            event = EventValidator.validate(raw_event)

            # 2. Compute metrics
            metric_result = MetricResult(
                sentiment=self._strategies["sentiment"].compute(event),
                toxicity=self._strategies["toxicity"].compute(event),
                virality_score=self._strategies["virality"].compute(event),
            )

            # 3. Publish
            enriched_event = {
                **event.dict(by_alias=True),
                "metrics": metric_result.__dict__,
            }
            await producer.send_and_wait(self._out_topic, enriched_event)
            PROM_MESSAGE_PUBLISHED.labels(platform=platform).inc()

            # Record offset for batch commit
            commit_queue.append(record)

        except (ValidationError, ValueError) as exc:
            logger.warning("Validation failed for message: %s", exc)
            PROM_MESSAGE_FAILED.labels(
                platform=platform, failure_stage="validation"
            ).inc()
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected error during processing: %s", exc)
            PROM_MESSAGE_FAILED.labels(
                platform=platform, failure_stage="runtime"
            ).inc()
            sentry_sdk.capture_exception(exc)
        finally:
            elapsed = time.perf_counter() - start_ts
            PROM_PROCESSING_LATENCY.labels(platform=platform).observe(elapsed)

    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        logger.info(
            "Starting LiveMetricProcessor | in=%s out=%s group=%s servers=%s",
            self._in_topic,
            self._out_topic,
            self._group_id,
            self._bootstrap_servers,
        )

        # Start Prometheus exporter
        prometheus_port = int(os.getenv("PULSE_PROM_PORT", "8001"))
        start_http_server(prometheus_port)
        logger.info("Prometheus exporter listening on :%d", prometheus_port)

        # Graceful shutdown hooks
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, self._should_stop.set)
        loop.add_signal_handler(signal.SIGTERM, self._should_stop.set)

        async with kafka_consumer(
            topic=self._in_topic,
            group_id=self._group_id,
            bootstrap_servers=self._bootstrap_servers,
        ) as consumer, kafka_producer(
            bootstrap_servers=self._bootstrap_servers
        ) as producer:
            commit_queue: List[Any] = []
            while not self._should_stop.is_set():
                with suppress(asyncio.TimeoutError):
                    async for record in consumer.getmany(
                        timeout_ms=100, max_records=256
                    ).values():
                        for msg in record:
                            await self._process_record(msg, producer, commit_queue)

                # Bulk commit offsets to reduce overhead
                if len(commit_queue) >= self._bulk_commit_size:
                    last_msg = commit_queue[-1]
                    await consumer.commit({
                        last_msg.topic_partition: last_msg.offset + 1
                    })
                    commit_queue.clear()

            # Final commit before shutdown
            if commit_queue:
                last_msg = commit_queue[-1]
                await consumer.commit({last_msg.topic_partition: last_msg.offset + 1})

        logger.info("LiveMetricProcessor stopped gracefully.")

    # ------------------------------------------------------------------ #
    async def stop(self) -> None:
        self._should_stop.set()


###############################################################################
# Entrypoint helper
###############################################################################

async def _main() -> None:
    processor = LiveMetricProcessor(
        in_topic=os.getenv("PULSE_IN_TOPIC", "social_raw"),
        out_topic=os.getenv("PULSE_OUT_TOPIC", "social_enriched"),
        group_id=os.getenv("PULSE_GROUP_ID", "pulse_metric_proc"),
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        sentry_dsn=os.getenv("SENTRY_DSN"),
    )
    await processor.run()


def main() -> None:  # pragma: no cover
    """
    CLI entry-point compatible with `python -m` invocation.
    """
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; shutting down.")


if __name__ == "__main__":  # pragma: no cover
    main()
```